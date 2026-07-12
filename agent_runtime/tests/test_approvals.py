import pytest
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.management import call_command
from pydantic import BaseModel
from io import StringIO

from aggregator.models import CrawlJob, Source
from agent_runtime.models import AgentRun


class RetryInput(BaseModel):
    source_id: int


class RetryOutput(BaseModel):
    queued: bool


@pytest.fixture
def approval_registry():
    from agent_runtime.research.tools import RiskLevel, ToolPermission, ToolRegistry, ToolSpec

    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="retry_source",
            version="1",
            input_model=RetryInput,
            output_model=RetryOutput,
            risk_level=RiskLevel.HIGH,
            permission=ToolPermission.STAFF,
            timeout_seconds=10,
            max_retries=0,
            idempotent=True,
            executor=lambda payload, _context: calls.append(payload.source_id) or {"queued": True},
        )
    )
    return registry, calls


@pytest.mark.django_db
def test_high_risk_tool_requires_staff_approval(approval_registry):
    from agent_runtime.models import AgentApproval
    from agent_runtime.research.approvals import request_tool_approval
    from agent_runtime.research.runtime import create_research_run

    registry, _calls = approval_registry
    run, _ = create_research_run("修复失败来源", "approval-request-01")
    approval = request_tool_approval(run, "retry_source", {"source_id": 7}, registry)
    run.refresh_from_db()

    assert approval.status == AgentApproval.Status.PENDING
    assert run.status == AgentRun.Status.WAITING_APPROVAL
    assert run.events.filter(event_type="approval.requested").exists()


@pytest.mark.django_db
def test_non_staff_cannot_decide_approval(approval_registry):
    from agent_runtime.research.approvals import decide_tool_approval, request_tool_approval
    from agent_runtime.research.runtime import create_research_run

    registry, _calls = approval_registry
    run, _ = create_research_run("修复失败来源", "approval-request-02")
    approval = request_tool_approval(run, "retry_source", {"source_id": 7}, registry)
    user = get_user_model().objects.create_user(username="student", password="test")

    with pytest.raises(PermissionError, match="staff permission"):
        decide_tool_approval(approval, user, approve=True, registry=registry)


@pytest.mark.django_db
def test_approved_tool_executes_exactly_once(approval_registry):
    from agent_runtime.models import AgentApproval
    from agent_runtime.research.approvals import decide_tool_approval, request_tool_approval
    from agent_runtime.research.runtime import create_research_run

    registry, calls = approval_registry
    run, _ = create_research_run("修复失败来源", "approval-request-03")
    approval = request_tool_approval(run, "retry_source", {"source_id": 9}, registry)
    staff = get_user_model().objects.create_user(username="operator", password="test", is_staff=True)

    first = decide_tool_approval(approval, staff, approve=True, registry=registry)
    second = decide_tool_approval(approval, staff, approve=True, registry=registry)

    assert first.status == AgentApproval.Status.EXECUTED
    assert second.status == AgentApproval.Status.EXECUTED
    assert calls == [9]
    assert first.result_json == {"queued": True}


@pytest.mark.django_db
def test_rejected_tool_never_executes(approval_registry):
    from agent_runtime.models import AgentApproval
    from agent_runtime.research.approvals import decide_tool_approval, request_tool_approval
    from agent_runtime.research.runtime import create_research_run

    registry, calls = approval_registry
    run, _ = create_research_run("修复失败来源", "approval-request-04")
    approval = request_tool_approval(run, "retry_source", {"source_id": 11}, registry)
    staff = get_user_model().objects.create_user(username="reviewer", password="test", is_staff=True)

    decided = decide_tool_approval(approval, staff, approve=False, registry=registry)

    assert decided.status == AgentApproval.Status.REJECTED
    assert calls == []


@pytest.mark.django_db
def test_retry_source_admin_tool_is_idempotent(monkeypatch):
    from agent_runtime.research.admin_tools import build_admin_registry
    from agent_runtime.research.tools import ToolContext

    source = Source.objects.create(
        name="待修复来源",
        url="https://broken.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
    )
    queued = []
    monkeypatch.setattr("aggregator.tasks.crawl_source.delay", lambda source_id: queued.append(source_id))
    registry = build_admin_registry()
    context = ToolContext(actor_is_staff=True, run_id="repair-run")

    first = registry.execute("retry_source", {"source_id": source.id}, context)
    second = registry.execute("retry_source", {"source_id": source.id}, context)

    assert first == {"queued": True, "job_id": CrawlJob.objects.get().id}
    assert second == {"queued": False, "job_id": CrawlJob.objects.get().id}
    assert queued == [source.id]


@pytest.mark.django_db
def test_admin_registry_can_diagnose_source_and_queue_reindex(monkeypatch):
    from agent_runtime.research.admin_tools import build_admin_registry
    from agent_runtime.research.tools import ToolContext

    source = Source.objects.create(
        name="诊断来源",
        url="https://diagnose.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
        failure_count=3,
    )
    queued = []
    monkeypatch.setattr("agent_runtime.tasks.index_content_item_rag.delay", queued.append)
    registry = build_admin_registry()
    context = ToolContext(actor_is_staff=True, run_id="admin-run")

    diagnosis = registry.execute("diagnose_source", {"source_id": source.id}, context)
    reindex = registry.execute("reindex_items", {"item_ids": [7, 7, 8]}, context)

    assert diagnosis["source_id"] == source.id
    assert diagnosis["failure_count"] == 3
    assert diagnosis["healthy"] is False
    assert reindex == {"queued_item_ids": [7, 8]}
    assert queued == [7, 8]


@pytest.mark.django_db
def test_request_agent_repair_command_creates_pending_approval():
    from agent_runtime.models import AgentApproval

    source = Source.objects.create(
        name="需要诊断的来源",
        url="https://repair.example.edu/",
        source_type=Source.SourceType.DEPARTMENT_SITE,
    )
    output = StringIO()

    call_command("request_agent_repair", "--source-id", source.id, stdout=output)

    approval = AgentApproval.objects.get()
    assert approval.tool_name == "retry_source"
    assert approval.payload_json == {"source_id": source.id}
    assert approval.status == AgentApproval.Status.PENDING
    assert str(approval.public_id) in output.getvalue()


def test_agent_approval_is_registered_in_admin():
    from agent_runtime.models import AgentApproval

    assert admin.site.is_registered(AgentApproval)
