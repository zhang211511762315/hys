from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from agent_runtime.models import AgentApproval, AgentRun

from .runtime import append_event
from .tools import RiskLevel, ToolContext, ToolPermission, ToolRegistry


def _approval_key(run: AgentRun, tool_name: str, payload: dict) -> str:
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]
    return f"{run.public_id}:{tool_name}:{digest}"


def request_tool_approval(
    run: AgentRun,
    tool_name: str,
    payload: dict,
    registry: ToolRegistry,
) -> AgentApproval:
    spec = registry.get(tool_name)
    if spec.permission != ToolPermission.STAFF or spec.risk_level != RiskLevel.HIGH:
        raise ValueError("approval is only valid for high-risk staff tools")
    spec.input_model.model_validate(payload)
    approval, created = AgentApproval.objects.get_or_create(
        idempotency_key=_approval_key(run, tool_name, payload),
        defaults={
            "run": run,
            "tool_name": tool_name,
            "tool_version": spec.version,
            "payload_json": payload,
        },
    )
    if created:
        run.status = AgentRun.Status.WAITING_APPROVAL
        run.current_node = "waiting_approval"
        run.save(update_fields=["status", "current_node", "updated_at"])
        append_event(run, "approval.requested", {"approval_id": str(approval.public_id), "tool": tool_name})
    return approval


def decide_tool_approval(
    approval: AgentApproval,
    user,
    *,
    approve: bool,
    registry: ToolRegistry,
) -> AgentApproval:
    if not getattr(user, "is_staff", False):
        raise PermissionError("approval decision requires staff permission")

    with transaction.atomic():
        locked = AgentApproval.objects.select_for_update().select_related("run").get(id=approval.id)
        if locked.status in {AgentApproval.Status.EXECUTED, AgentApproval.Status.REJECTED, AgentApproval.Status.FAILED}:
            return locked
        locked.decided_by = user
        locked.decided_at = timezone.now()
        if not approve:
            locked.status = AgentApproval.Status.REJECTED
            locked.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
            locked.run.status = AgentRun.Status.CANCELLED
            locked.run.finished_at = timezone.now()
            locked.run.save(update_fields=["status", "finished_at", "updated_at"])
            append_event(locked.run, "approval.rejected", {"approval_id": str(locked.public_id)})
            return locked
        locked.status = AgentApproval.Status.EXECUTING
        locked.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])

    try:
        result = registry.execute(
            locked.tool_name,
            locked.payload_json,
            ToolContext(actor_is_staff=True, run_id=str(locked.run.public_id)),
        )
    except Exception as exc:
        locked.status = AgentApproval.Status.FAILED
        locked.error_message = str(exc)[:2000]
        locked.save(update_fields=["status", "error_message", "updated_at"])
        locked.run.status = AgentRun.Status.FAILED
        locked.run.finished_at = timezone.now()
        locked.run.save(update_fields=["status", "finished_at", "updated_at"])
        append_event(locked.run, "approval.failed", {"approval_id": str(locked.public_id)})
        return locked

    locked.status = AgentApproval.Status.EXECUTED
    locked.result_json = result
    locked.save(update_fields=["status", "result_json", "updated_at"])
    locked.run.status = AgentRun.Status.SUCCEEDED
    locked.run.finished_at = timezone.now()
    locked.run.save(update_fields=["status", "finished_at", "updated_at"])
    append_event(locked.run, "approval.executed", {"approval_id": str(locked.public_id), "tool": locked.tool_name})
    return locked
