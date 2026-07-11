from django.contrib import admin

from .models import AgentRun, AgentStep, ContentChunk, LLMUsageEvent, RagCitation, RagMessage, RagSession


class AgentStepInline(admin.TabularInline):
    model = AgentStep
    extra = 0
    readonly_fields = ("created_at", "updated_at", "duration_ms")


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("kind", "trigger", "status", "started_at", "finished_at", "total_cost_cny")
    list_filter = ("kind", "status")
    search_fields = ("trigger", "error_message")
    readonly_fields = ("created_at", "updated_at")
    inlines = [AgentStepInline]


@admin.register(ContentChunk)
class ContentChunkAdmin(admin.ModelAdmin):
    list_display = ("content_item", "chunk_index", "search_document_id", "updated_at")
    search_fields = ("text", "content_item__title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RagSession)
class RagSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "session_key", "total_input_tokens", "total_output_tokens", "total_cost_cny", "updated_at")
    search_fields = ("title", "session_key")
    readonly_fields = ("created_at", "updated_at")


admin.site.register(RagMessage)
admin.site.register(RagCitation)
admin.site.register(LLMUsageEvent)
