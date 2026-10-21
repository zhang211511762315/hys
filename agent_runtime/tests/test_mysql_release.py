"""Real independent MySQL connections; synthetic inputs and no task delivery."""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch
import uuid
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, connections, close_old_connections
from django.test import override_settings
from agent_runtime.admission import admit, AdmissionError, _deliver
from agent_runtime.models import AgentRun

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def mysql_only():
    if connection.vendor != 'mysql':
        pytest.skip('requires isolated MySQL 8.4')
    cache.clear()


def parallel(user_ids, keys):
    barrier = threading.Barrier(len(keys))
    def call(pair):
        close_old_connections()
        try:
            user = get_user_model().objects.get(pk=pair[0]); barrier.wait(timeout=10)
            try:
                run, created = admit(user, 'synthetic', pair[1], '192.0.2.1')
                return ('ok', run.pk, created)
            except AdmissionError as exc:
                return ('rejected', exc.status, False)
        finally: connections.close_all()
    with ThreadPoolExecutor(len(keys)) as pool:
        with patch('agent_runtime.admission._deliver', side_effect=lambda run: run):
            return list(pool.map(call, zip(user_ids, keys)))


@override_settings(RESEARCH_AGENT_DAILY_LIMIT=10, RESEARCH_AGENT_CONCURRENT_LIMIT=1)
def test_user_lock_serializes_concurrent_admission():
    user = get_user_model().objects.create_user(username='synthetic')
    result = parallel([user.pk, user.pk], ['key-a', 'key-b'])
    assert sum(r[0] == 'ok' for r in result) == 1
    assert AgentRun.objects.filter(ownership__owner=user).count() == 1


@override_settings(RESEARCH_AGENT_DAILY_LIMIT=10, RESEARCH_AGENT_CONCURRENT_LIMIT=2)
def test_same_key_two_connections_create_once():
    user = get_user_model().objects.create_user(username='synthetic')
    result = parallel([user.pk, user.pk], ['shared-key', 'shared-key'])
    assert all(r[0] == 'ok' for r in result)
    assert len({r[1] for r in result}) == 1
    assert sum(r[2] for r in result) == 1


def test_cross_user_collision_never_returns_foreign_run():
    from django.core.exceptions import PermissionDenied
    one = get_user_model().objects.create_user(username='one')
    two = get_user_model().objects.create_user(username='two')
    with patch('agent_runtime.admission._deliver', side_effect=lambda run: run):
        run, _ = admit(one, 'synthetic', 'shared-key', '192.0.2.1')
        with pytest.raises(PermissionDenied): admit(two, 'synthetic', 'shared-key', '192.0.2.2')
    assert AgentRun.objects.get(pk=run.pk).owner_id == one.pk


def test_dispatch_failure_refunds_and_same_key_retry_uses_same_row():
    user = get_user_model().objects.create_user(username='synthetic')
    with patch('agent_runtime.admission.execute_research_run_task.delay', side_effect=[RuntimeError('synthetic'), None]) as deliver:
        with pytest.raises(AdmissionError): admit(user, 'synthetic', 'retry', '192.0.2.1')
        first = AgentRun.objects.get(client_request_id='retry')
        run, created = admit(user, 'synthetic', 'retry', '192.0.2.1')
    assert not created and run.pk == first.pk and deliver.call_count == 2
    assert run.dispatch_meta['state'] == 'sent'


def test_parallel_delivery_publishes_only_once():
    user = get_user_model().objects.create_user(username='synthetic')
    run = create_owned_run(owner=user, kind='rag', status='queued', dispatch_meta={'state': 'pending'})
    entered = threading.Event(); release = threading.Event()
    def publish(*args): entered.set(); assert release.wait(5)
    def first():
        close_old_connections()
        try: return _deliver(AgentRun.objects.get(pk=run.pk)).pk
        finally: connections.close_all()
    with patch('agent_runtime.admission.execute_research_run_task.delay', side_effect=publish) as delivery:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(first)
            try:
                assert entered.wait(5)
                with pytest.raises(AdmissionError) as error: _deliver(run)
                assert error.value.status == 503
            finally: release.set()
            assert future.result(5) == run.pk
        assert delivery.call_count == 1


def test_release_gate_checks_real_mysql_constraints(monkeypatch):
    # --nomigrations creates the final model schema in the synthetic test DB;
    # only its migration ledger is mocked, never the physical constraints.
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.db.migrations.recorder import MigrationRecorder
    monkeypatch.delenv('MYSQL_ROOT_PASSWORD', raising=False)
    with patch.object(MigrationRecorder.Migration.objects, 'filter') as applied:
        applied.return_value.exists.return_value = True
        call_command('release_check', verbosity=0)
        with patch.object(connection.introspection, 'get_constraints', return_value={}):
            with pytest.raises(CommandError, match='foreign key'): call_command('release_check')


def create_owned_run(owner, **kwargs):
    from django.db import transaction
    from agent_runtime.models import ResearchRunOwnership
    with transaction.atomic():
        run = AgentRun.objects.create(**kwargs)
        ResearchRunOwnership.objects.create(run=run, owner=owner)
        return run
