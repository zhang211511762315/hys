import json
import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from asgiref.sync import async_to_sync
from django.core.cache import cache
from django.db import IntegrityError
from django.db.models.query import QuerySet
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone

from aggregator.models import Category, ContentItem, Source


@pytest.fixture(autouse=True)
def clear_research_cache():
    cache.clear()
@pytest.fixture
def deadline_item():
    source = Source.objects.create(
        name="教务处",
        url="https://jwc.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
    )
    category = Category.objects.create(name="通知", slug="notice")
    return ContentItem.objects.create(
        source=source,
        category=category,
        title="创新竞赛报名通知",
        canonical_url="https://jwc.example.edu/contest",
        summary="创新竞赛报名截止时间为2026年8月1日。",
        content_text="请参赛学生在2026年8月1日前完成报名。",
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    )


@pytest.mark.django_db
def test_create_research_run_is_idempotent():
    from agent_runtime.models import AgentEvent
    from agent_runtime.research.runtime import create_research_run

    first, first_created = create_research_run("查询竞赛截止日期", "request-001")
    second, second_created = create_research_run("不同文本不会覆盖原任务", "request-001")

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.goal == "查询竞赛截止日期"
    assert AgentEvent.objects.filter(run=first, event_type="run.created").count() == 1


@pytest.mark.django_db
def test_non_http_research_creation_and_replay_always_persist_valid_request_ids():
    from agent_runtime.research.runtime import create_research_run, replay_research_run

    run, _ = create_research_run("管理命令风格的研究运行", "repair-command-request")
    invalid_run, _ = create_research_run(
        "无效请求 ID 仍由服务器生成",
        "invalid-runtime-request",
        request_id="not-a-uuid",
    )
    replay_without_id = replay_research_run(run)
    replay_with_invalid_id = replay_research_run(run, request_id="not-a-uuid")

    for candidate in (run, invalid_run, replay_without_id, replay_with_invalid_id):
        assert isinstance(candidate.request_id, uuid.UUID)


@pytest.mark.django_db
def test_idempotent_reuse_backfills_legacy_null_request_id_without_overwriting_existing_id():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    legacy = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="legacy-null-request-id",
        goal="迁移前运行",
        trigger="research_api",
        status=AgentRun.Status.QUEUED,
        request_id=None,
    )
    supplied_request_id = uuid.uuid4()

    reused, created = create_research_run(
        "重试不覆盖原任务",
        legacy.client_request_id,
        request_id=supplied_request_id,
    )

    assert created is False
    assert reused.id == legacy.id
    assert reused.request_id == supplied_request_id

    original_request_id = uuid.uuid4()
    current = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="current-request-id",
        request_id=original_request_id,
    )
    reused_current, current_created = create_research_run(
        "重试保留原始关联",
        current.client_request_id,
        request_id=uuid.uuid4(),
    )

    assert current_created is False
    assert reused_current.request_id == original_request_id


@pytest.mark.django_db
def test_legacy_null_request_id_backfill_observes_the_concurrent_winner(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    legacy = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="racing-legacy-request-id",
        request_id=None,
    )
    concurrent_winner = uuid.uuid4()
    losing_retry_id = uuid.uuid4()
    original_update = QuerySet.update
    compared_and_set = []

    def race_before_compare_and_set(queryset, **kwargs):
        if queryset.model is AgentRun and kwargs.get("request_id") == losing_retry_id:
            compared_and_set.append(True)
            original_update(
                AgentRun.objects.filter(id=legacy.id, request_id__isnull=True),
                request_id=concurrent_winner,
            )
        return original_update(queryset, **kwargs)

    monkeypatch.setattr(QuerySet, "update", race_before_compare_and_set)

    reused, created = create_research_run(
        "竞争重试",
        legacy.client_request_id,
        request_id=losing_retry_id,
    )

    assert created is False
    assert compared_and_set == [True]
    assert reused.request_id == concurrent_winner


@pytest.mark.django_db
def test_legacy_null_backfill_uses_a_locking_current_read_after_losing_race(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    legacy = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="mysql-snapshot-legacy-request-id",
        request_id=None,
    )
    concurrent_winner = uuid.uuid4()
    losing_retry_id = uuid.uuid4()
    original_update = QuerySet.update
    original_select_for_update = QuerySet.select_for_update
    locking_reads = []

    def race_before_compare_and_set(queryset, **kwargs):
        if queryset.model is AgentRun and kwargs.get("request_id") == losing_retry_id:
            original_update(
                AgentRun.objects.filter(id=legacy.id, request_id__isnull=True),
                request_id=concurrent_winner,
            )
        return original_update(queryset, **kwargs)

    def observe_locking_read(queryset, *args, **kwargs):
        if queryset.model is AgentRun:
            locking_reads.append(True)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "update", race_before_compare_and_set)
    monkeypatch.setattr(QuerySet, "select_for_update", observe_locking_read)

    reused, created = create_research_run(
        "MySQL 快照竞争重试",
        legacy.client_request_id,
        request_id=losing_retry_id,
    )

    assert created is False
    assert locking_reads == [True]
    assert reused.request_id == concurrent_winner


@pytest.mark.django_db
def test_duplicate_key_recovery_uses_a_locking_current_read_for_the_winner(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    winner = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="concurrent-first-submission",
        request_id=uuid.uuid4(),
    )
    duplicate_attempted = []
    locking_reads = []
    original_select_for_update = QuerySet.select_for_update
    original_first = QuerySet.first
    hide_initial_lookup = [True]

    def raise_duplicate_key(**_kwargs):
        duplicate_attempted.append(True)
        raise IntegrityError("duplicate client request id")

    def observe_locking_read(queryset, *args, **kwargs):
        if queryset.model is AgentRun:
            locking_reads.append(True)
        return original_select_for_update(queryset, *args, **kwargs)

    def hide_winner_from_initial_lookup(queryset):
        if queryset.model is AgentRun and hide_initial_lookup[0]:
            hide_initial_lookup[0] = False
            return None
        return original_first(queryset)

    monkeypatch.setattr(AgentRun.objects, "create", raise_duplicate_key)
    monkeypatch.setattr(QuerySet, "select_for_update", observe_locking_read)
    monkeypatch.setattr(QuerySet, "first", hide_winner_from_initial_lookup)

    recovered, created = create_research_run(
        "并发首提交恢复",
        winner.client_request_id,
        request_id=uuid.uuid4(),
    )

    assert duplicate_attempted == [True]
    assert locking_reads == [True]
    assert created is False
    assert recovered.id == winner.id
    assert recovered.request_id == winner.request_id


@pytest.mark.django_db
def test_execute_research_run_persists_trace_and_terminal_state(deadline_item, settings):
    settings.MEILISEARCH_URL = ""
    from agent_runtime.models import AgentRun, ToolInvocation
    from agent_runtime.research.runtime import create_research_run, execute_research_run

    run, _ = create_research_run("整理创新竞赛报名截止时间", "request-002")
    result = execute_research_run(run.id)
    run.refresh_from_db()

    assert result["status"] == "succeeded"
    assert run.status == AgentRun.Status.SUCCEEDED
    assert run.current_node == "finalize"
    assert run.state_json["answer"]["citations"][0]["item_id"] == deadline_item.id
    assert list(run.events.values_list("sequence", flat=True)) == list(range(1, run.events.count() + 1))
    assert set(run.events.values_list("event_type", flat=True)) >= {
        "run.created",
        "plan.created",
        "tool.completed",
        "verification.passed",
        "run.completed",
    }
    assert ToolInvocation.objects.filter(run=run, status=ToolInvocation.Status.SUCCEEDED).count() == 3


@pytest.mark.django_db
def test_research_runtime_persists_tool_attempt_events(deadline_item, settings):
    settings.MEILISEARCH_URL = ""
    from agent_runtime.models import ToolInvocation
    from agent_runtime.research.runtime import create_research_run, execute_research_run

    run, _ = create_research_run("整理创新竞赛报名截止时间", "attempt-trace-001")
    execute_research_run(run.id)

    invocations = list(ToolInvocation.objects.filter(run=run).order_by("step_id", "attempt"))
    assert invocations
    assert all(invocation.attempt == 1 for invocation in invocations)
    assert all(invocation.duration_ms >= 0 for invocation in invocations)
    assert set(run.events.values_list("event_type", flat=True)) >= {"tool.started", "tool.completed"}


@pytest.mark.django_db
def test_research_run_api_enqueues_once_for_same_client_request(monkeypatch):
    from agent_runtime.models import AgentRun

    calls = []
    monkeypatch.setattr(
        "agent_runtime.views.execute_research_run_task.delay",
        lambda run_id: calls.append(run_id),
    )
    client = Client()
    payload = {"goal": "比较近期就业活动", "client_request_id": "browser-request-1"}

    first = client.post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")
    second = client.post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    assert calls == [str(AgentRun.objects.get().public_id)]


@pytest.mark.django_db
def test_research_api_retry_backfills_legacy_null_request_correlation(monkeypatch):
    from agent_runtime.models import AgentRun

    legacy = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="legacy-http-retry-request",
        goal="迁移前 HTTP 运行",
        trigger="research_api",
        status=AgentRun.Status.QUEUED,
        request_id=None,
    )
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    request_id = str(uuid.uuid4())

    response = Client().post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "重试", "client_request_id": legacy.client_request_id}),
        content_type="application/json",
        HTTP_X_REQUEST_ID=request_id,
    )

    legacy.refresh_from_db()
    assert response.status_code == 200
    assert response.json()["run_id"] == str(legacy.public_id)
    assert legacy.request_id == uuid.UUID(request_id)


@pytest.mark.django_db
def test_authenticated_duplicate_admission_locks_user_then_current_run_and_skips_quota(monkeypatch):
    from agent_runtime.models import AgentRun, ResearchAdmissionKey

    user = get_user_model().objects.create_user(username="idempotent-admission", password="safe-test-password-123")
    run = AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id="admission-duplicate-request",
        request_id=uuid.uuid4(),
    )
    locking_order = []
    original_select_for_update = QuerySet.select_for_update

    def observe_lock(queryset, *args, **kwargs):
        if queryset.model in {get_user_model(), ResearchAdmissionKey, AgentRun}:
            locking_order.append(queryset.model)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", observe_lock)
    monkeypatch.setattr(
        "agent_runtime.views._consume_daily_research_quota",
        lambda _client_ip: (_ for _ in ()).throw(AssertionError("duplicate must skip quota admission")),
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "重复请求", "client_request_id": run.client_request_id}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == str(run.public_id)
    assert locking_order == [ResearchAdmissionKey, get_user_model()]


@pytest.mark.django_db
def test_authenticated_first_admission_locks_before_quota_and_creates_once(monkeypatch):
    from agent_runtime.models import AgentRun, ResearchAdmissionKey

    user = get_user_model().objects.create_user(username="first-admission", password="safe-test-password-123")
    locking_order = []
    original_select_for_update = QuerySet.select_for_update

    def observe_lock(queryset, *args, **kwargs):
        if queryset.model in {get_user_model(), ResearchAdmissionKey, AgentRun}:
            locking_order.append(queryset.model)
        return original_select_for_update(queryset, *args, **kwargs)

    def quota_after_locks(_client_ip):
        assert locking_order == [ResearchAdmissionKey, get_user_model()]
        return True

    monkeypatch.setattr(QuerySet, "select_for_update", observe_lock)
    monkeypatch.setattr("agent_runtime.views._consume_daily_research_quota", quota_after_locks)
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    client = Client()
    client.force_login(user)

    response = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "首次请求", "client_request_id": "admission-first-request"}),
        content_type="application/json",
    )

    assert response.status_code == 202
    assert AgentRun.objects.filter(client_request_id="admission-first-request").count() == 1


@pytest.mark.django_db
def test_anonymous_key_lock_rejects_true_quota_without_creating_a_run(monkeypatch):
    from agent_runtime.models import AgentRun, ResearchAdmissionKey

    client_request_id = "anonymous-quota-rejection"
    locking_order = []
    original_select_for_update = QuerySet.select_for_update

    def observe_lock(queryset, *args, **kwargs):
        if queryset.model is ResearchAdmissionKey:
            locking_order.append(queryset.model)
        return original_select_for_update(queryset, *args, **kwargs)

    def reject_after_key_lock(_client_ip):
        assert locking_order == [ResearchAdmissionKey]
        return False

    monkeypatch.setattr(QuerySet, "select_for_update", observe_lock)
    monkeypatch.setattr("agent_runtime.views._consume_daily_research_quota", reject_after_key_lock)

    response = Client().post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "匿名并发重试", "client_request_id": client_request_id}),
        content_type="application/json",
    )

    assert response.status_code == 429
    assert not AgentRun.objects.filter(client_request_id=client_request_id).exists()
    assert not ResearchAdmissionKey.objects.filter(client_request_id=client_request_id).exists()


@pytest.mark.django_db
def test_rejected_unique_anonymous_admissions_do_not_accumulate_keys(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey

    monkeypatch.setattr("agent_runtime.views._consume_daily_research_quota", lambda _client_ip: False)
    client = Client()

    for index in range(5):
        response = client.post(
            "/api/v1/research-runs",
            data=json.dumps({"goal": "超额请求", "client_request_id": f"rejected-key-{index}"}),
            content_type="application/json",
        )
        assert response.status_code == 429

    assert ResearchAdmissionKey.objects.count() == 0


@pytest.mark.django_db
def test_exception_during_admission_cleans_up_orphan_key(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey

    monkeypatch.setattr("agent_runtime.views._consume_daily_research_quota", lambda _client_ip: True)
    monkeypatch.setattr(
        "agent_runtime.views.create_research_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("runtime failed")),
    )
    client_request_id = "exception-admission-key"

    with pytest.raises(RuntimeError, match="runtime failed"):
        Client().post(
            "/api/v1/research-runs",
            data=json.dumps({"goal": "异常清理", "client_request_id": client_request_id}),
            content_type="application/json",
        )

    assert not ResearchAdmissionKey.objects.filter(client_request_id=client_request_id).exists()


@pytest.mark.django_db
def test_retry_after_true_rejection_recreates_key_and_creates_one_run(monkeypatch):
    from agent_runtime.models import AgentRun, ResearchAdmissionKey

    quota_results = iter([False, True])
    monkeypatch.setattr("agent_runtime.views._consume_daily_research_quota", lambda _client_ip: next(quota_results))
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    client_request_id = "retry-after-rejection"
    payload = {"goal": "拒绝后重试", "client_request_id": client_request_id}

    rejected = Client().post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")
    accepted = Client().post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")

    assert rejected.status_code == 429
    assert accepted.status_code == 202
    assert AgentRun.objects.filter(client_request_id=client_request_id).count() == 1
    assert ResearchAdmissionKey.objects.filter(client_request_id=client_request_id).count() == 1


@pytest.mark.django_db
def test_stale_orphan_admission_key_cleanup_preserves_active_and_run_backed_keys():
    from agent_runtime.models import AgentRun, ResearchAdmissionKey
    from agent_runtime.services import cleanup_stale_research_admission_keys

    stale_orphan = ResearchAdmissionKey.objects.create(client_request_id="stale-orphan-key")
    fresh_orphan = ResearchAdmissionKey.objects.create(client_request_id="fresh-orphan-key")
    backed_key = ResearchAdmissionKey.objects.create(client_request_id="run-backed-key")
    AgentRun.objects.create(
        kind=AgentRun.Kind.RAG,
        client_request_id=backed_key.client_request_id,
        request_id=uuid.uuid4(),
    )
    stale_at = timezone.now() - timedelta(seconds=301)
    ResearchAdmissionKey.objects.filter(id__in=[stale_orphan.id, backed_key.id]).update(updated_at=stale_at)

    deleted = cleanup_stale_research_admission_keys(now=timezone.now(), minimum_age_seconds=300)

    assert deleted == 1
    assert not ResearchAdmissionKey.objects.filter(id=stale_orphan.id).exists()
    assert ResearchAdmissionKey.objects.filter(id=fresh_orphan.id).exists()
    assert ResearchAdmissionKey.objects.filter(id=backed_key.id).exists()


@pytest.mark.django_db
def test_admission_key_retries_when_duplicate_recovery_row_was_deleted(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey
    from agent_runtime.views import _get_research_admission_key

    original_create = ResearchAdmissionKey.objects.create
    original_get = ResearchAdmissionKey.objects.get
    create_attempts = []
    get_attempts = []

    def create_after_first_duplicate(**kwargs):
        create_attempts.append(True)
        if len(create_attempts) == 1:
            raise IntegrityError("duplicate key")
        return original_create(**kwargs)

    def missing_after_duplicate(**kwargs):
        get_attempts.append(True)
        if len(get_attempts) == 1:
            raise ResearchAdmissionKey.DoesNotExist
        return original_get(**kwargs)

    monkeypatch.setattr(ResearchAdmissionKey.objects, "create", create_after_first_duplicate)
    monkeypatch.setattr(ResearchAdmissionKey.objects, "get", missing_after_duplicate)

    key = _get_research_admission_key("recreated-after-delete")

    assert len(create_attempts) == 2
    assert get_attempts == [True]
    assert key.client_request_id == "recreated-after-delete"


@pytest.mark.django_db
def test_admission_key_creation_exhaustion_raises_sanitized_error(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey
    from agent_runtime.views import _get_research_admission_key

    monkeypatch.setattr(
        ResearchAdmissionKey.objects,
        "create",
        lambda **_kwargs: (_ for _ in ()).throw(IntegrityError("duplicate key")),
    )
    monkeypatch.setattr(
        ResearchAdmissionKey.objects,
        "get",
        lambda **_kwargs: (_ for _ in ()).throw(ResearchAdmissionKey.DoesNotExist),
    )

    with pytest.raises(RuntimeError, match="research admission key unavailable"):
        _get_research_admission_key("exhausted-admission-key")


@pytest.mark.django_db
def test_admission_key_exhaustion_returns_private_503_and_cleans_orphan(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey
    from agent_runtime.views import ResearchAdmissionUnavailable

    client_request_id = "http-exhausted-admission-key"
    ResearchAdmissionKey.objects.create(client_request_id=client_request_id)
    monkeypatch.setattr(
        "agent_runtime.views._get_research_admission_key",
        lambda _client_request_id: (_ for _ in ()).throw(ResearchAdmissionUnavailable("internal retry details")),
    )
    request_id = str(uuid.uuid4())

    response = Client().post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "不可用响应", "client_request_id": client_request_id}),
        content_type="application/json",
        HTTP_X_REQUEST_ID=request_id,
    )

    assert response.status_code == 503
    assert response.json() == {"error": "admission temporarily unavailable"}
    assert response["X-Request-ID"] == request_id
    assert "internal retry details" not in response.content.decode()
    assert not ResearchAdmissionKey.objects.filter(client_request_id=client_request_id).exists()


@pytest.mark.django_db
def test_anonymous_same_key_admission_lock_preserves_new_and_duplicate_responses(monkeypatch):
    from agent_runtime.models import ResearchAdmissionKey

    client_request_id = "anonymous-same-key-admission"
    locked_keys = []
    original_select_for_update = QuerySet.select_for_update

    def observe_key_lock(queryset, *args, **kwargs):
        if queryset.model is ResearchAdmissionKey:
            locked_keys.append(True)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", observe_key_lock)
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    payload = {"goal": "匿名同键", "client_request_id": client_request_id}

    first = Client().post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")
    second = Client().post("/api/v1/research-runs", data=json.dumps(payload), content_type="application/json")

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    assert locked_keys == [True, True]
    assert ResearchAdmissionKey.objects.filter(client_request_id=client_request_id).count() == 1


@pytest.mark.django_db
def test_different_authenticated_users_same_key_do_not_take_agent_run_gap_locks(monkeypatch):
    from agent_runtime.models import AgentRun, ResearchAdmissionKey

    first_user = get_user_model().objects.create_user(username="gap-lock-first", password="safe-test-password-123")
    second_user = get_user_model().objects.create_user(username="gap-lock-second", password="safe-test-password-123")
    locking_agent_queries = []
    locked_key_ids = []
    original_select_for_update = QuerySet.select_for_update

    def observe_locks(queryset, *args, **kwargs):
        if queryset.model is AgentRun:
            locking_agent_queries.append(str(queryset.query.where))
        if queryset.model is ResearchAdmissionKey:
            locked_key_ids.append(str(queryset.query.where))
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", observe_locks)
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    first_client = Client()
    first_client.force_login(first_user)
    second_client = Client()
    second_client.force_login(second_user)
    first_payload = {"goal": "不同键用户一", "client_request_id": "different-user-first-key"}
    second_payload = {"goal": "不同键用户二", "client_request_id": "different-user-second-key"}

    first = first_client.post("/api/v1/research-runs", data=json.dumps(first_payload), content_type="application/json")
    second = second_client.post("/api/v1/research-runs", data=json.dumps(second_payload), content_type="application/json")

    assert first.status_code == 202
    assert second.status_code == 202
    assert all("client_request_id" not in query for query in locking_agent_queries)
    assert len(locked_key_ids) == 2
    assert ResearchAdmissionKey.objects.count() == 2


@pytest.mark.django_db
def test_research_request_ids_are_persisted_and_idempotent_reuse_keeps_original(monkeypatch, caplog):
    from agent_runtime.models import AgentRun

    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    caplog.set_level(logging.INFO, logger="zhongbei_info.observability")
    client = Client()
    original_request_id = str(uuid.uuid4())
    retry_request_id = str(uuid.uuid4())
    payload = {"goal": "查询关联 ID", "client_request_id": "correlation-request-01"}

    first = client.post(
        "/api/v1/research-runs",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_REQUEST_ID=original_request_id,
    )
    second = client.post(
        "/api/v1/research-runs",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_REQUEST_ID=retry_request_id,
    )

    run = AgentRun.objects.get(public_id=first.json()["run_id"])
    assert run.request_id == uuid.UUID(original_request_id)
    assert second.json()["run_id"] == first.json()["run_id"]
    assert run.request_id != uuid.UUID(retry_request_id)
    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "zhongbei_info.observability" and json.loads(record.getMessage()).get("path") == "/api/v1/research-runs"
    ]
    assert [record["run_id"] for record in records] == [str(run.public_id), str(run.public_id)]


@pytest.mark.django_db
def test_replay_persists_the_replay_request_id(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    original, _ = create_research_run("查询关联 ID", "replay-correlation-01")
    replay_request_id = str(uuid.uuid4())
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)

    response = Client().post(
        f"/api/v1/research-runs/{original.public_id}/replay",
        HTTP_X_REQUEST_ID=replay_request_id,
    )

    replay = AgentRun.objects.exclude(id=original.id).get()
    assert response.status_code == 202
    assert replay.request_id == uuid.UUID(replay_request_id)


@pytest.mark.django_db
def test_correlation_middleware_validates_ids_adds_headers_and_logs_only_allowlisted_fields(caplog):
    request_id = str(uuid.uuid4())
    caplog.set_level(logging.INFO, logger="zhongbei_info.observability")
    client = Client()

    valid = client.get("/healthz", HTTP_X_REQUEST_ID=request_id)
    invalid = client.get("/missing-route", HTTP_X_REQUEST_ID="not-a-uuid")

    assert valid["X-Request-ID"] == request_id
    assert invalid.status_code == 404
    assert uuid.UUID(invalid["X-Request-ID"])
    completion_records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "zhongbei_info.observability"
        and set(json.loads(record.getMessage())) == {"request_id", "run_id", "method", "path", "status", "duration_ms"}
    ]
    assert len(completion_records) == 2
    assert completion_records[0]["request_id"] == request_id
    assert completion_records[0]["run_id"] is None
    assert completion_records[1]["status"] == 404


@pytest.mark.django_db
def test_streaming_ask_gets_correlation_header_and_safe_runtime_creation_log(monkeypatch, caplog):
    expected_request_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    caplog.set_level(logging.INFO, logger="zhongbei_info.observability")

    def fake_answer_question_events(*_args, request_id=None, on_run_created=None, **_kwargs):
        assert request_id == expected_request_id
        assert callable(on_run_created)
        on_run_created(SimpleNamespace(public_id=run_id))
        yield {"type": "done"}

    monkeypatch.setattr("agent_runtime.views.answer_question_events", fake_answer_question_events)

    response = Client().post(
        "/ask/stream/",
        data=json.dumps({"question": "private question must not be logged"}),
        content_type="application/json",
        HTTP_X_REQUEST_ID=expected_request_id,
    )
    async def collect_stream():
        return [chunk async for chunk in response.streaming_content]

    async_to_sync(collect_stream)()

    assert response["X-Request-ID"] == expected_request_id
    lifecycle_records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "zhongbei_info.observability.lifecycle"
    ]
    assert lifecycle_records == [{"request_id": expected_request_id, "run_id": run_id}]
    payloads = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "zhongbei_info.observability"
    ]
    completion_record = next(
        payload
        for payload in payloads
        if payload.get("path") == "/ask/stream/" and payload.get("status") == 200
    )
    assert completion_record["run_id"] == run_id and completion_record["status"] == 200
    assert all("private question must not be logged" not in record.getMessage() for record in caplog.records)


@pytest.mark.django_db
def test_legacy_rag_runtime_gets_a_request_id_without_an_http_request(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.services import answer_question_events

    monkeypatch.setattr("agent_runtime.services.retrieve_contexts", lambda _question: [])
    monkeypatch.setattr("agent_runtime.services.build_rag_graph", lambda: None)
    monkeypatch.setattr(
        "agent_runtime.services._generate_answer",
        lambda _prompt, _contexts, _estimate: ("回答", {}, "budget_or_key_unavailable"),
    )

    list(answer_question_events("无 HTTP 的运行"))

    run = AgentRun.objects.get(trigger="ask_page")
    assert isinstance(run.request_id, uuid.UUID)


@pytest.mark.django_db
@override_settings(SECURE_SSL_REDIRECT=True)
def test_https_redirect_has_correlation_header_and_completion_log(caplog):
    request_id = str(uuid.uuid4())
    caplog.set_level(logging.INFO, logger="zhongbei_info.observability")

    response = Client().get("/healthz", HTTP_X_REQUEST_ID=request_id)

    assert response.status_code == 301
    assert response["X-Request-ID"] == request_id
    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "zhongbei_info.observability"
    ]
    assert records == [
        {
            "request_id": request_id,
            "run_id": None,
            "method": "GET",
            "path": "/healthz",
            "status": 301,
            "duration_ms": records[0]["duration_ms"],
        }
    ]


@pytest.mark.django_db
def test_research_event_stream_includes_stable_sse_ids():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import append_event, create_research_run

    run, _ = create_research_run("查询校园通知", "request-events")
    append_event(run, "plan.created", {"step_count": 2})
    run.status = AgentRun.Status.SUCCEEDED
    run.save(update_fields=["status", "updated_at"])
    client = Client()

    response = client.get(f"/api/v1/research-runs/{run.public_id}/events")
    body = b"".join(response.streaming_content).decode()

    assert response.status_code == 200
    assert "id: 1\nevent: run.created" in body
    assert "id: 2\nevent: plan.created" in body
    assert 'data: {"step_count": 2}' in body


@pytest.mark.django_db(transaction=True)
def test_research_event_stream_observes_events_created_after_connection():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import append_event, create_research_run

    run, _ = create_research_run("查询实时事件", "request-live-events")
    response = Client().get(f"/api/v1/research-runs/{run.public_id}/events")
    iterator = iter(response.streaming_content)

    first = next(iterator).decode()
    append_event(run, "answer.delta", {"text": "第一段"})
    run.status = AgentRun.Status.SUCCEEDED
    run.save(update_fields=["status", "updated_at"])
    second = next(iterator).decode()

    assert "event: run.created" in first
    assert "event: answer.delta" in second


@pytest.mark.django_db
def test_research_api_enforces_daily_limit_for_new_requests(monkeypatch, settings):
    settings.RESEARCH_AGENT_DAILY_LIMIT = 1
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", lambda _run_id: None)
    client = Client()

    first = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "查询就业信息", "client_request_id": "daily-limit-0001"}),
        content_type="application/json",
    )
    second = client.post(
        "/api/v1/research-runs",
        data=json.dumps({"goal": "查询科研活动", "client_request_id": "daily-limit-0002"}),
        content_type="application/json",
    )

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"] == "daily limit exceeded"


@pytest.mark.django_db
def test_cancel_research_run_marks_terminal_and_emits_event():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    run, _ = create_research_run("查询通知", "cancel-request-01")
    response = Client().post(f"/api/v1/research-runs/{run.public_id}/cancel")
    run.refresh_from_db()

    assert response.status_code == 200
    assert run.status == AgentRun.Status.CANCELLED
    assert run.events.filter(event_type="run.cancelled").exists()


@pytest.mark.django_db
def test_cancel_is_idempotent_after_terminal_state():
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    run, _ = create_research_run("终态取消", "cancel-terminal-01")
    run.status = AgentRun.Status.SUCCEEDED
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "updated_at"])

    response = Client().post(f"/api/v1/research-runs/{run.public_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(run.public_id),
        "status": AgentRun.Status.SUCCEEDED,
        "cancelled": False,
    }
    assert not run.events.filter(event_type="run.cancelled").exists()


@pytest.mark.django_db
def test_replay_creates_new_run_with_frozen_versions(monkeypatch):
    from agent_runtime.models import AgentRun
    from agent_runtime.research.runtime import create_research_run

    original, _ = create_research_run("查询就业通知", "replay-original-01")
    original.graph_version = "research-v7"
    original.prompt_version = "prompt-v3"
    original.status = AgentRun.Status.SUCCEEDED
    original.save(update_fields=["graph_version", "prompt_version", "status", "updated_at"])
    queued = []
    monkeypatch.setattr("agent_runtime.views.execute_research_run_task.delay", queued.append)

    response = Client().post(f"/api/v1/research-runs/{original.public_id}/replay")

    assert response.status_code == 202
    replay = AgentRun.objects.exclude(id=original.id).get()
    assert replay.goal == original.goal
    assert replay.graph_version == "research-v7"
    assert replay.prompt_version == "prompt-v3"
    assert replay.replay_of_id == original.id
    assert replay.events.get(event_type="run.replayed").payload_json["source_run_id"] == str(original.public_id)
    assert queued == [str(replay.public_id)]


@pytest.mark.django_db
def test_session_memory_is_used_only_when_secure_mode_enabled(settings):
    from agent_runtime.models import RagMessage, RagSession
    from agent_runtime.research.memory import resolve_goal_with_memory

    session = RagSession.objects.create(session_key="memory-session", title="就业活动")
    RagMessage.objects.create(session=session, role=RagMessage.Role.USER, content="帮我找近期就业活动")
    RagMessage.objects.create(session=session, role=RagMessage.Role.ASSISTANT, content="找到了三项就业活动")

    settings.RESEARCH_AGENT_SESSION_MEMORY_ENABLED = False
    assert resolve_goal_with_memory("这些活动的截止时间", session) == "这些活动的截止时间"

    settings.RESEARCH_AGENT_SESSION_MEMORY_ENABLED = True
    resolved = resolve_goal_with_memory("这些活动的截止时间", session)
    assert "帮我找近期就业活动" in resolved
    assert resolved.endswith("当前目标：这些活动的截止时间")


@pytest.mark.django_db
def test_research_page_uses_post_api_and_event_stream():
    response = Client().get("/research/")
    html = response.content.decode()

    assert response.status_code == 200
    assert 'fetch("/api/v1/research-runs"' in html
    assert 'method: "POST"' in html
    assert "new EventSource(payload.events_url)" in html
    assert "当前公网为 HTTP 演示环境" not in html


@pytest.mark.django_db
def test_research_page_exposes_cancel_replay_and_stream_error_states():
    html = Client().get("/research/").content.decode()

    assert 'id="cancel-run"' in html
    assert 'id="replay-run"' in html
    assert "activeStream.onerror" in html
    assert "请求过于频繁" in html
    assert 'fetch(`/api/v1/research-runs/${activeRunId}/cancel`' in html
    assert 'fetch(`/api/v1/research-runs/${runId}/replay`' in html
    assert "?q=" not in html


@pytest.mark.django_db
def test_agent_dashboard_displays_research_latency_percentiles():
    from agent_runtime.models import ToolInvocation
    from agent_runtime.research.runtime import create_research_run

    run, _ = create_research_run("延迟统计", "latency-dashboard")
    for index, duration in enumerate([10, 20, 100], start=1):
        ToolInvocation.objects.create(
            run=run,
            step_id=f"step-{index}",
            tool_name="search_public_content",
            status=ToolInvocation.Status.SUCCEEDED,
            duration_ms=duration,
        )

    html = Client().get("/agent/").content.decode()

    assert "工具延迟 P50" in html
    assert ">20 ms<" in html
    assert "工具延迟 P95" in html
    assert ">100 ms<" in html


@pytest.mark.django_db
def test_agent_dashboard_shows_only_latest_aggregate_evalops_comparison():
    from agent_runtime.models import AgentRun, EvaluationCaseResult, EvaluationRun

    comparison_id = uuid4()
    baseline = EvaluationRun.objects.create(
        agent_run=AgentRun.objects.create(kind=AgentRun.Kind.EVAL),
        comparison_id=comparison_id,
        dataset_version="strategy-dashboard-test",
        strategy="single_agent",
        status=EvaluationRun.Status.SUCCEEDED,
        metrics_json={
            "case_count": 1,
            "plan_valid_count": 1,
            "tool_selection_correct_count": 1,
            "plan_valid_rate": 1.0,
            "tool_selection_accuracy": 1.0,
            "unsafe_tool_selection_count": 0,
            "total_cost_cny": "0",
            "p95_latency_ms": 1,
        },
    )
    candidate = EvaluationRun.objects.create(
        agent_run=AgentRun.objects.create(kind=AgentRun.Kind.EVAL),
        comparison_id=comparison_id,
        dataset_version="strategy-dashboard-test",
        strategy="multi_agent_experimental",
        status=EvaluationRun.Status.SUCCEEDED,
        metrics_json={
            "case_count": 1,
            "plan_valid_count": 1,
            "tool_selection_correct_count": 1,
            "plan_valid_rate": 1.0,
            "tool_selection_accuracy": 1.0,
            "unsafe_tool_selection_count": 0,
            "total_cost_cny": "0",
            "p95_latency_ms": 2,
        },
    )
    EvaluationCaseResult.objects.create(
        evaluation_run=candidate,
        case_id="private-case",
        category="security",
        goal="private case goal must never render",
        expected_task_type="search",
        expected_tools=["search_public_content"],
        actual_task_type="search",
        actual_tools=["search_public_content"],
        status=EvaluationCaseResult.Status.SUCCEEDED,
        detail_json={"stage_trace": [{"stage": "planner"}]},
    )

    html = Client().get("/agent/").content.decode()

    assert "EvalOps 策略对比" in html
    assert "候选" in html
    assert "单Agent" in html
    assert "多Agent（实验）" in html
    assert "private case goal must never render" not in html
    assert "private-case" not in html
    assert baseline.case_results.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("candidate_status, candidate_metrics", [
    (
        "failed",
        {
            "case_count": 1,
            "plan_valid_count": 1,
            "tool_selection_correct_count": 1,
            "plan_valid_rate": 1.0,
            "tool_selection_accuracy": 1.0,
            "unsafe_tool_selection_count": 0,
            "total_cost_cny": "0",
            "p95_latency_ms": 1,
        },
    ),
    (
        "succeeded",
        {
            "plan_valid_rate": 1.0,
            "tool_selection_accuracy": 1.0,
            "unsafe_tool_selection_count": 0,
            "total_cost_cny": "0",
            "p95_latency_ms": 1,
        },
    ),
])
def test_agent_dashboard_never_labels_failed_or_incomplete_pair_candidate(
    candidate_status,
    candidate_metrics,
):
    from agent_runtime.models import AgentRun, EvaluationRun

    comparison_id = uuid4()
    baseline_metrics = {
        "case_count": 1,
        "plan_valid_count": 1,
        "tool_selection_correct_count": 1,
        "plan_valid_rate": 1.0,
        "tool_selection_accuracy": 1.0,
        "unsafe_tool_selection_count": 0,
        "total_cost_cny": "0",
        "p95_latency_ms": 1,
    }
    EvaluationRun.objects.create(
        agent_run=AgentRun.objects.create(kind=AgentRun.Kind.EVAL),
        comparison_id=comparison_id,
        dataset_version="not-ready-dashboard-test",
        strategy="single_agent",
        status=EvaluationRun.Status.SUCCEEDED,
        metrics_json=baseline_metrics,
    )
    EvaluationRun.objects.create(
        agent_run=AgentRun.objects.create(kind=AgentRun.Kind.EVAL),
        comparison_id=comparison_id,
        dataset_version="not-ready-dashboard-test",
        strategy="multi_agent_experimental",
        status=candidate_status,
        metrics_json=candidate_metrics,
    )

    html = Client().get("/agent/").content.decode()

    assert "EvalOps 策略对比" in html
    assert "候选" not in html
    assert "未就绪" in html


@pytest.mark.django_db
def test_agent_dashboard_never_labels_nonexact_comparison_pair_candidate():
    from agent_runtime.models import AgentRun, EvaluationRun

    comparison_id = uuid4()
    metrics = {
        "case_count": 1,
        "plan_valid_count": 1,
        "tool_selection_correct_count": 1,
        "plan_valid_rate": 1.0,
        "tool_selection_accuracy": 1.0,
        "unsafe_tool_selection_count": 0,
        "total_cost_cny": "0",
        "p95_latency_ms": 1,
    }
    for strategy in ["single_agent", "multi_agent_experimental", "single_agent"]:
        EvaluationRun.objects.create(
            agent_run=AgentRun.objects.create(kind=AgentRun.Kind.EVAL),
            comparison_id=comparison_id,
            dataset_version="duplicate-dashboard-test",
            strategy=strategy,
            status=EvaluationRun.Status.SUCCEEDED,
            metrics_json=metrics,
        )

    html = Client().get("/agent/").content.decode()

    assert "候选" not in html
    assert "未就绪" in html


@pytest.mark.django_db
def test_agent_dashboard_displays_freshness_and_failure_breakdown():
    from aggregator.models import CrawlFailure, CrawlJob, Source

    source = Source.objects.create(
        name="失败统计来源",
        url="https://failure-dashboard.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
        last_success_at=timezone.datetime(2026, 7, 12, 8, 0, tzinfo=timezone.get_current_timezone()),
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url)
    CrawlFailure.objects.create(
        crawl_job=job,
        source=source,
        url=source.url,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
    )

    html = Client().get("/agent/").content.decode()

    assert "数据新鲜度" in html
    assert "永久失败" in html
    assert "最后成功抓取" in html


@pytest.mark.django_db
def test_agent_dashboard_separates_actionable_and_acknowledged_permanent_failures():
    from aggregator.models import CrawlFailure, CrawlJob, Source

    source = Source.objects.create(
        name="已确认展示来源",
        url="https://dashboard-acknowledged.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
    )
    job = CrawlJob.objects.create(source=source, target_url=source.url)
    CrawlFailure.objects.create(
        crawl_job=job,
        source=source,
        url=source.url,
        failure_class=CrawlFailure.FailureClass.PERMANENT,
        permanent=True,
        http_status=410,
        acknowledged_at=timezone.now(),
        acknowledged_status=410,
        acknowledged_note="Confirmed by operator",
    )

    html = Client().get("/agent/").content.decode()

    assert "待处理失败 0" in html
    assert "已确认永久失败 1" in html
