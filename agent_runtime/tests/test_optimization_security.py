import json
import uuid
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, override_settings

from agent_runtime import admission
from agent_runtime.access import client_ip
from agent_runtime.models import AgentRun
from agent_runtime.research.runtime import create_research_run, execute_research_run

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolate_cache():
    cache.clear()


@pytest.fixture
def actor(client, monkeypatch):
    user = get_user_model().objects.create_user('synthetic-user', password='synthetic-pass')
    client.force_login(user)
    monkeypatch.setattr(admission.execute_research_run_task, 'delay', Mock())
    return user


def create(client, key=None):
    return client.post('/api/v1/research-runs', json.dumps({
        'goal': 'synthetic public information', 'client_request_id': key or str(uuid.uuid4())}),
        content_type='application/json')


def test_anonymous_all_research_api_methods_are_401_before_csrf():
    c = Client(enforce_csrf_checks=True)
    key = str(uuid.uuid4())
    for method, path in [('post', ''), ('get', '/'+key), ('get', '/'+key+'/events'),
                         ('post', '/'+key+'/cancel'), ('post', '/'+key+'/replay')]:
        response = getattr(c, method)('/api/v1/research-runs'+path)
        assert response.status_code == 401
        assert response.json()['error'] == 'authentication required'
    assert AgentRun.objects.count() == 0


def test_authenticated_writes_still_require_csrf(actor):
    c = Client(enforce_csrf_checks=True); c.force_login(actor)
    assert c.post('/api/v1/research-runs').status_code == 403


def test_owner_and_idempotency_are_bound_to_authenticated_user(client, actor):
    key = str(uuid.uuid4())
    response = create(client, key)
    assert response.status_code == 202
    run = AgentRun.objects.get(public_id=response.json()['run_id'])
    assert run.owner == actor
    assert create(client, key).status_code == 200
    admission.execute_research_run_task.delay.assert_called_once()
    other = get_user_model().objects.create_user('another-user')
    client.force_login(other)
    assert create(client, key).status_code == 404
    for suffix, method in [('', 'get'), ('/events', 'get'), ('/cancel', 'post'), ('/replay', 'post')]:
        assert getattr(client, method)(f'/api/v1/research-runs/{run.public_id}'+suffix).status_code == 404


def test_legacy_runs_are_staff_only(client, actor):
    run = AgentRun.objects.create(goal='synthetic legacy', status=AgentRun.Status.SUCCEEDED)
    assert client.get(f'/api/v1/research-runs/{run.public_id}').status_code == 404
    actor.is_staff = True; actor.save()
    assert client.get(f'/api/v1/research-runs/{run.public_id}').status_code == 200
    run.refresh_from_db(); assert run.owner_id is None


def test_replay_shares_daily_and_concurrent_admission(client, actor, settings):
    settings.RESEARCH_AGENT_DAILY_LIMIT = 2
    settings.RESEARCH_AGENT_CONCURRENT_LIMIT = 1
    response = create(client); run = AgentRun.objects.get(public_id=response.json()['run_id'])
    assert client.post(f'/api/v1/research-runs/{run.public_id}/replay').status_code == 429
    run.status = AgentRun.Status.SUCCEEDED; run.save()
    assert client.post(f'/api/v1/research-runs/{run.public_id}/replay').status_code == 202
    AgentRun.objects.filter(ownership__owner=actor).update(status=AgentRun.Status.SUCCEEDED)
    assert create(client).status_code == 429


def test_dispatch_failure_is_not_success_and_late_delivery_cannot_execute(client, actor, monkeypatch):
    admission.execute_research_run_task.delay.side_effect = RuntimeError('synthetic broker full')
    assert create(client).status_code == 503
    run = AgentRun.objects.get(ownership__owner=actor)
    assert run.status == AgentRun.Status.FAILED
    assert run.trigger == 'research_dispatch_failed'
    with monkeypatch.context() as m:
        m.setattr('agent_runtime.research.runtime.build_default_registry', lambda: pytest.fail('must not execute'))
        assert execute_research_run(run.pk)['status'] == AgentRun.Status.FAILED


def test_direct_xff_untrusted_and_proxy_must_supply_single_valid_ip():
    factory = RequestFactory()
    with override_settings(TRUSTED_PROXY_IPS=['127.0.0.1']):
        assert client_ip(factory.get('/', REMOTE_ADDR='198.51.100.10', HTTP_X_FORWARDED_FOR='203.0.113.8')) == '198.51.100.10'
        assert client_ip(factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='203.0.113.8')) == '203.0.113.8'
        assert client_ip(factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='203.0.113.8, 198.51.100.10')) == '127.0.0.1'


def test_login_works_for_nonstaff_and_rejects_external_redirect(client, actor):
    client.logout()
    assert client.get('/accounts/login/').status_code == 200
    response = client.post('/accounts/login/', {'username': actor.username, 'password': 'synthetic-pass', 'next': 'https://outside.invalid/'})
    assert response.status_code == 302 and response.url == '/research/'
    assert client.get('/research/').status_code == 200


def test_owner_input_is_rejected(client, actor):
    response = client.post('/api/v1/research-runs', json.dumps({'goal': 'fixture', 'client_request_id': str(uuid.uuid4()), 'owner_id': actor.pk}), content_type='application/json')
    assert response.status_code == 400
    assert AgentRun.objects.count() == 0


def test_runtime_refuses_cross_owner_id_reuse(actor):
    key = str(uuid.uuid4())
    create_research_run('fixture', key, owner=actor)
    other = get_user_model().objects.create_user('other-runtime-user')
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied): create_research_run('fixture', key, owner=other)


def test_throttled_login_never_checks_password(client, actor, monkeypatch):
    client.logout()
    cache.set('account-login-fails:127.0.0.1', 8)
    check = Mock(side_effect=AssertionError('throttled passwords must not be verified'))
    monkeypatch.setattr('django.contrib.auth.forms.AuthenticationForm.clean', check)
    response = client.post('/accounts/login/', {'username': actor.username, 'password': 'synthetic-pass'})
    assert response.status_code == 429
    check.assert_not_called()


def test_same_key_can_recover_a_confirmed_dispatch_failure(client, actor):
    key = str(uuid.uuid4())
    admission.execute_research_run_task.delay.side_effect = RuntimeError('synthetic broker failure')
    assert create(client, key).status_code == 503
    admission.execute_research_run_task.delay.side_effect = None
    assert create(client, key).status_code == 200
    run = AgentRun.objects.get(ownership__owner=actor)
    assert run.status == AgentRun.Status.QUEUED
    assert run.dispatch_meta['state'] == 'sent'
    assert AgentRun.objects.count() == 1


def test_pending_publication_is_not_reported_as_success(client, actor):
    key = str(uuid.uuid4())
    run, _ = create_research_run('fixture', key, owner=actor)
    from django.utils import timezone
    run.dispatch_meta = {'state': 'sending', 'started': timezone.now().timestamp(), 'ip': '127.0.0.1'}
    run.save()
    assert create(client, key).status_code == 503
    admission.execute_research_run_task.delay.assert_not_called()
    run.dispatch_meta['started'] -= 61; run.save()
    assert create(client, key).status_code == 200
    admission.execute_research_run_task.delay.assert_called_once()


def test_cancelling_running_work_keeps_concurrency_slot(client, actor, settings):
    settings.RESEARCH_AGENT_CONCURRENT_LIMIT = 1
    response = create(client)
    run = AgentRun.objects.get(public_id=response.json()['run_id'])
    run.status = AgentRun.Status.PLANNING; run.save()
    result = client.post(f'/api/v1/research-runs/{run.public_id}/cancel')
    assert result.json()['status'] == 'cancelling'
    assert create(client).status_code == 429


def test_redelivered_interrupted_work_becomes_terminal_without_model_reexecution(actor):
    from agent_runtime.tasks import execute_research_run_task
    from django.utils import timezone
    run = create_owned_run(owner=actor, status=AgentRun.Status.PLANNING,
                                  dispatch_meta={'execution_started': timezone.now().timestamp()-140})
    execute_research_run_task.push_request(delivery_info={'redelivered': True}, retries=0)
    try:
        result = execute_research_run_task.run(str(run.public_id))
    finally:
        execute_research_run_task.pop_request()
    assert result['status'] == AgentRun.Status.FAILED
    run.refresh_from_db(); assert run.status == AgentRun.Status.FAILED


def test_page_cache_full_is_best_effort_but_admission_fails_closed(client, actor, monkeypatch):
    from redis.exceptions import OutOfMemoryError
    from zhongbei_info.page_cache import BestEffortPageCache
    from django.core.cache.backends.redis import RedisCache
    backend = BestEffortPageCache('redis://127.0.0.1:1/2', {})
    monkeypatch.setattr(RedisCache, 'set', Mock(side_effect=OutOfMemoryError('synthetic full')))
    assert backend.set('fixture', 'value') is False
    monkeypatch.setattr(admission.cache, 'add', Mock(side_effect=OutOfMemoryError('synthetic full')))
    assert create(client).status_code == 503
    assert AgentRun.objects.count() == 0


def create_owned_run(owner, **kwargs):
    from django.db import transaction
    from agent_runtime.models import ResearchRunOwnership
    with transaction.atomic():
        run = AgentRun.objects.create(**kwargs)
        ResearchRunOwnership.objects.create(run=run, owner=owner)
        return run


def test_user_deletion_preserves_run_and_clears_ownership(actor):
    from agent_runtime.models import ResearchRunOwnership
    run, _ = create_research_run('synthetic', str(uuid.uuid4()), owner=actor)
    actor.delete()
    run.refresh_from_db()
    assert run.owner_id is None
    assert ResearchRunOwnership.objects.get(run=run).owner_id is None


def test_ownership_creation_is_atomic(actor, monkeypatch):
    from agent_runtime.models import ResearchRunOwnership
    key = str(uuid.uuid4())
    def failed(**kwargs):
        raise RuntimeError('synthetic ownership write failure')
    monkeypatch.setattr(ResearchRunOwnership.objects, 'create', failed)
    with pytest.raises(RuntimeError):
        create_research_run('synthetic', key, owner=actor)
    assert not AgentRun.objects.filter(client_request_id=key).exists()


def test_public_dashboard_does_not_expose_private_run_details(client, actor):
    run, _ = create_research_run('private fixture goal', str(uuid.uuid4()), owner=actor)
    run.metrics_json = {'private_detail': 'synthetic-private-metric'}
    run.error_message = 'synthetic-private-error'
    run.save()
    client.logout()
    html = client.get('/agent/').content.decode()
    assert 'synthetic-private-metric' not in html
    assert 'synthetic-private-error' not in html
    client.force_login(actor)
    html = client.get('/agent/').content.decode()
    assert 'synthetic-private-metric' not in html
    actor.is_staff = True
    actor.save()
    assert 'synthetic-private-metric' in client.get('/agent/').content.decode()
