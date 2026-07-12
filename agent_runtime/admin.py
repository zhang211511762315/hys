from django.contrib import admin

from .models import (
    AgentApproval,
    AgentEvent,
    AgentRun,
    AgentStep,
    ContentChunk,
    LLMUsageEvent,
    MemoryEntry,
    RagCitation,
    RagMessage,
    RagSession,
    ToolInvocation,
)
from .research.admin_tools import build_admin_registry
from .research.approvals import decide_tool_approval


class AgentStepInline(admin.TabularInline):
    model = AgentStep
    extra = 0
    readonly_fields = ("created_at", "updated_at", "duration_ms")


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("public_id", "kind", "trigger", "status", "started_at", "finished_at", "total_cost_cny")
    list_filter = ("kind", "status")
    search_fields = ("trigger", "error_message")
    readonly_fields = ("created_at", "updated_at")
    inlines = [AgentStepInline]


@admin.register(AgentApproval)
class AgentApprovalAdmin(admin.ModelAdmin):
    list_display = ("public_id", "tool_name", "status", "run", "decided_by", "created_at")
    list_filter = ("status", "tool_name")
    readonly_fields = (
        "public_id",
        "run",
        "tool_name",
        "tool_version",
        "payload_json",
        "result_json",
        "idempotency_key",
        "status",
        "error_message",
        "decided_at",
        "decided_by",
        "created_at",
        "updated_at",
    )
    actions = ("approve_selected", "reject_selected")

    @admin.action(description="批准并执行所选工具动作")
    def approve_selected(self, request, queryset):
        registry = build_admin_registry()
        for approval in queryset:
            decide_tool_approval(approval, request.user, approve=True, registry=registry)

    @admin.action(description="拒绝所选工具动作")
    def reject_selected(self, request, queryset):
        registry = build_admin_registry()
        for approval in queryset:
            decide_tool_approval(approval, request.user, approve=False, registry=registry)


@admin.register(ContentChunk)
class ContentChunkAdmin(admin.ModelAdmin):
    list_display = ("content_item", "chunk_index", "search_document_id", "updated_at")
    search_fields = ("text", "content_item__title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RagSession)
class RagSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "session_key", "total_input_tokens", "total_output_tokens", "total_cost_cny", "expires_at", "updated_at")
    search_fields = ("title", "session_key")
    readonly_fields = ("created_at", "updated_at")


admin.site.register(RagMessage)
admin.site.register(MemoryEntry)
admin.site.register(RagCitation)
admin.site.register(LLMUsageEvent)
admin.site.register(AgentEvent)
admin.site.register(ToolInvocation)
