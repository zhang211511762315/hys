"""Shared authenticated admission. Database owner lock serializes user quotas."""
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .public_workspace import shared_user
from .models import AgentRun
from .research.runtime import create_research_run, _reuse_research_run, normalized_request_id, append_event
from .tasks import execute_research_run_task


class AdmissionError(Exception):
    def __init__(self, message, status=429):
        self.status = status
        super().__init__(message)


def visible_runs(user):
    qs = AgentRun.objects.all()
    return qs if user.is_staff else qs.filter(ownership__owner=user)


def _ip_key(ip):
    return f'research-agent:daily:{timezone.localdate().isoformat()}:{ip}'


def _reserve_ip(ip, limit):
    try:
        if cache.add(_ip_key(ip), 1, timeout=26*3600):
            return
        count = cache.incr(_ip_key(ip))
        if count <= limit:
            return
        cache.decr(_ip_key(ip))
    except Exception as exc:
        raise AdmissionError('admission temporarily unavailable', 503) from exc
    raise AdmissionError('daily limit exceeded')


def _release_ip(ip):
    try:
        cache.decr(_ip_key(ip))
    except Exception:
        # Conservatively retain quota if the cache is unavailable.
        pass


def admit(user, goal, request_key, ip, request_id=None, replay_of=None):
    reserved = False
    created = False
    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            existing = AgentRun.objects.filter(client_request_id=request_key).first()
            retry_dispatch = False
            if existing:
                if existing.owner_id != user.pk:
                    raise PermissionDenied('request id unavailable')
                if replay_of and existing.replay_of_id != replay_of.pk:
                    raise AdmissionError('request id conflict', 409)
                existing = _reuse_research_run(existing, normalized_request_id(request_id))
                retry_dispatch = existing.trigger == 'research_dispatch_failed' and existing.status == AgentRun.Status.FAILED
            if existing and not retry_dispatch:
                run = existing
            else:
                limit = max(0, int(settings.RESEARCH_AGENT_DAILY_LIMIT))
                owned = AgentRun.objects.filter(Q(ownership__isnull=False) | Q(trigger__startswith='research')) if shared_user(user) else AgentRun.objects.filter(ownership__owner=user)
                owned = owned.exclude(trigger='research_dispatch_failed')
                if not limit or owned.filter(created_at__date=timezone.localdate()).count() >= limit:
                    raise AdmissionError('daily limit exceeded')
                active = [AgentRun.Status.QUEUED, AgentRun.Status.PLANNING, AgentRun.Status.EXECUTING,
                          AgentRun.Status.VERIFYING, AgentRun.Status.RUNNING, AgentRun.Status.WAITING_APPROVAL,
                          AgentRun.Status.CANCELLING]
                if owned.filter(status__in=active).count() >= settings.RESEARCH_AGENT_CONCURRENT_LIMIT:
                    raise AdmissionError('concurrent limit exceeded')
                _reserve_ip(ip, limit)
                reserved = True
                if retry_dispatch:
                    run = existing
                    run.status = AgentRun.Status.QUEUED
                    run.finished_at = None
                    run.error_message = ''
                else:
                    run, created = create_research_run(goal, request_key, request_id=request_id, owner=user)
                    if not created:
                        _release_ip(ip)
                        reserved = False
                run.trigger = 'research_replay' if replay_of or run.replay_of_id else 'research_api'
                if replay_of:
                    run.replay_of = replay_of
                    run.graph_version, run.prompt_version = replay_of.graph_version, replay_of.prompt_version
                run.dispatch_meta = {'state': 'pending', 'ip': ip}
                run.save(update_fields=['trigger', 'replay_of', 'graph_version', 'prompt_version',
                                        'status', 'finished_at', 'error_message', 'dispatch_meta', 'updated_at'])
                if replay_of and created:
                    append_event(run, 'run.replayed', {'source_run_id': str(replay_of.public_id), 'status': run.status})
    except BaseException:
        if reserved:
            _release_ip(ip)
        raise
    return _deliver(run), created


def _deliver(run):
    # Durable publication state permits same-key retries after a process crash.
    token = uuid.uuid4().hex
    with transaction.atomic():
        current = AgentRun.objects.select_for_update().get(pk=run.pk)
        meta = dict(current.dispatch_meta or {})
        if current.status == AgentRun.Status.FAILED and current.trigger == 'research_dispatch_failed':
            raise AdmissionError('task dispatch unavailable', 503)
        if current.status != AgentRun.Status.QUEUED or meta.get('state') == 'sent':
            return current
        now = timezone.now().timestamp()
        if meta.get('state') == 'sending' and now - meta.get('started', now) < 60:
            raise AdmissionError('task dispatch pending; retry same request', 503)
        meta.update(state='sending', token=token, started=now)
        current.dispatch_meta = meta
        current.save(update_fields=['dispatch_meta', 'updated_at'])
    try:
        execute_research_run_task.delay(str(run.public_id))
    except Exception as exc:
        failed = False
        with transaction.atomic():
            current = AgentRun.objects.select_for_update().get(pk=run.pk)
            meta = dict(current.dispatch_meta or {})
            if current.status == AgentRun.Status.QUEUED and meta.get('token') == token:
                current.status = AgentRun.Status.FAILED
                current.trigger = 'research_dispatch_failed'
                current.error_message = 'task dispatch unavailable'
                current.finished_at = timezone.now()
                meta['state'] = 'failed'
                current.dispatch_meta = meta
                current.save(update_fields=['status', 'trigger', 'error_message', 'finished_at', 'dispatch_meta', 'updated_at'])
                failed = True
        if failed:
            _release_ip(meta.get('ip', 'unknown'))
            raise AdmissionError('task dispatch unavailable', 503) from exc
        if current.status == AgentRun.Status.QUEUED:
            raise AdmissionError('task dispatch pending; retry same request', 503) from exc
        return current  # Execution has been confirmed; never overwrite its state.
    with transaction.atomic():
        current = AgentRun.objects.select_for_update().get(pk=run.pk)
        meta = dict(current.dispatch_meta or {})
        if meta.get('token') == token:
            meta['state'] = 'sent'
            current.dispatch_meta = meta
            current.save(update_fields=['dispatch_meta', 'updated_at'])
    return current
