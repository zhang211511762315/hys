from decimal import Decimal
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AgentRun(TimeStampedModel):
    class Kind(models.TextChoices):
        CRAWL = "crawl", "抓取"
        RAG = "rag", "问答"
        SELF_HEAL = "self_heal", "自愈"
        INDEX = "index", "索引"
        EVAL = "eval", "评测"

    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        PLANNING = "planning", "规划中"
        EXECUTING = "executing", "执行中"
        VERIFYING = "verifying", "验证中"
        WAITING_APPROVAL = "waiting_approval", "等待审批"
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    kind = models.CharField(max_length=40, choices=Kind.choices)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    client_request_id = models.CharField(max_length=120, unique=True, null=True, blank=True)
    goal = models.TextField(blank=True)
    trigger = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    metrics_json = models.JSONField(default=dict, blank=True)
    state_json = models.JSONField(default=dict, blank=True)
    current_node = models.CharField(max_length=80, blank=True)
    graph_version = models.CharField(max_length=40, default="research-v1")
    prompt_version = models.CharField(max_length=40, default="research-v1")
    replay_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replays",
    )
    total_cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent运行"
        verbose_name_plural = "Agent运行"

    def finish(self, status: str, error_message: str = "", metrics: dict | None = None) -> None:
        self.status = status
        self.finished_at = timezone.now()
        if error_message:
            self.error_message = error_message[:2000]
        if metrics:
            self.metrics_json = {**(self.metrics_json or {}), **metrics}
        self.save(update_fields=["status", "finished_at", "error_message", "metrics_json", "updated_at"])


class AgentStep(TimeStampedModel):
    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        SKIPPED = "skipped", "跳过"

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    name = models.CharField(max_length=120)
    tool_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    input_summary = models.TextField(blank=True)
    output_summary = models.TextField(blank=True)
    cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Agent步骤"
        verbose_name_plural = "Agent步骤"

    def finish(self, status: str, output_summary: str = "", error_message: str = "") -> None:
        now = timezone.now()
        self.status = status
        self.finished_at = now
        self.duration_ms = max(0, int((now - self.started_at).total_seconds() * 1000))
        if output_summary:
            self.output_summary = output_summary[:2000]
        if error_message:
            self.error_message = error_message[:2000]
        self.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "output_summary",
                "error_message",
                "updated_at",
            ]
        )


class AgentEvent(TimeStampedModel):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=80)
    payload_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["run", "sequence"], name="unique_agent_event_sequence")
        ]


class ToolInvocation(TimeStampedModel):
    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        DENIED = "denied", "拒绝"

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="tool_invocations")
    step_id = models.CharField(max_length=40)
    tool_name = models.CharField(max_length=80)
    tool_version = models.CharField(max_length=40, default="1")
    risk_level = models.CharField(max_length=20, default="low")
    permission = models.CharField(max_length=20, default="public")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    attempt = models.PositiveIntegerField(default=1)
    input_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["run", "step_id"], name="unique_agent_tool_step")
        ]


class AgentApproval(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待审批"
        EXECUTING = "executing", "执行中"
        EXECUTED = "executed", "已执行"
        REJECTED = "rejected", "已拒绝"
        FAILED = "failed", "失败"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="approvals")
    tool_name = models.CharField(max_length=80)
    tool_version = models.CharField(max_length=40, default="1")
    payload_json = models.JSONField(default=dict, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_approval_decisions",
    )

    class Meta:
        ordering = ["-created_at"]


class ContentChunk(TimeStampedModel):
    content_item = models.ForeignKey("aggregator.ContentItem", on_delete=models.CASCADE, related_name="rag_chunks")
    chunk_index = models.PositiveIntegerField()
    text = models.TextField()
    search_document_id = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["content_item_id", "chunk_index"]
        constraints = [
            models.UniqueConstraint(fields=["content_item", "chunk_index"], name="unique_rag_chunk_index")
        ]
        verbose_name = "RAG知识块"
        verbose_name_plural = "RAG知识块"

    def __str__(self):
        return f"{self.content_item_id}:{self.chunk_index}"


class RagSession(TimeStampedModel):
    session_key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rag_sessions",
    )
    title = models.CharField(max_length=160, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    total_input_tokens = models.PositiveIntegerField(default=0)
    total_output_tokens = models.PositiveIntegerField(default=0)
    total_cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "RAG会话"
        verbose_name_plural = "RAG会话"

    def __str__(self):
        return self.title or self.session_key


class MemoryEntry(TimeStampedModel):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memory_entries")
    source_session = models.ForeignKey(
        RagSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memory_entries",
    )
    content = models.CharField(max_length=1000)
    consented_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "长期记忆"
        verbose_name_plural = "长期记忆"


class RagMessage(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "user", "用户"
        ASSISTANT = "assistant", "助手"

    session = models.ForeignKey(RagSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    model = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "RAG消息"
        verbose_name_plural = "RAG消息"


class RagCitation(TimeStampedModel):
    message = models.ForeignKey(RagMessage, on_delete=models.CASCADE, related_name="citations")
    content_item = models.ForeignKey("aggregator.ContentItem", on_delete=models.CASCADE)
    title = models.CharField(max_length=300)
    source_name = models.CharField(max_length=160, blank=True)
    url = models.URLField(max_length=500)
    snippet = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "RAG引用"
        verbose_name_plural = "RAG引用"


class LLMUsageEvent(TimeStampedModel):
    class Status(models.TextChoices):
        ESTIMATED = "estimated", "估算"
        FINAL = "final", "最终"
        BLOCKED = "blocked", "预算拦截"
        FALLBACK = "fallback", "兜底"

    session = models.ForeignKey(RagSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_events")
    message = models.ForeignKey(RagMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_events")
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=80)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    budget_remaining_cny = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ESTIMATED)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "LLM用量事件"
        verbose_name_plural = "LLM用量事件"
