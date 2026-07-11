from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("aggregator", "0010_source_source_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("crawl", "抓取"), ("rag", "问答"), ("self_heal", "自愈"), ("index", "索引")], max_length=40)),
                ("trigger", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(choices=[("running", "运行中"), ("succeeded", "成功"), ("failed", "失败")], default="running", max_length=20)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("metrics_json", models.JSONField(blank=True, default=dict)),
                ("total_cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("error_message", models.TextField(blank=True)),
            ],
            options={"verbose_name": "Agent运行", "verbose_name_plural": "Agent运行", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RagSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("session_key", models.CharField(max_length=64, unique=True)),
                ("title", models.CharField(blank=True, max_length=160)),
                ("total_input_tokens", models.PositiveIntegerField(default=0)),
                ("total_output_tokens", models.PositiveIntegerField(default=0)),
                ("total_cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
            ],
            options={"verbose_name": "RAG会话", "verbose_name_plural": "RAG会话", "ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="AgentStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("tool_name", models.CharField(blank=True, max_length=120)),
                ("status", models.CharField(choices=[("running", "运行中"), ("succeeded", "成功"), ("failed", "失败"), ("skipped", "跳过")], default="running", max_length=20)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("input_summary", models.TextField(blank=True)),
                ("output_summary", models.TextField(blank=True)),
                ("cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("error_message", models.TextField(blank=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="agent_runtime.agentrun")),
            ],
            options={"verbose_name": "Agent步骤", "verbose_name_plural": "Agent步骤", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="ContentChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("chunk_index", models.PositiveIntegerField()),
                ("text", models.TextField()),
                ("search_document_id", models.CharField(max_length=80, unique=True)),
                ("content_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rag_chunks", to="aggregator.contentitem")),
            ],
            options={"verbose_name": "RAG知识块", "verbose_name_plural": "RAG知识块", "ordering": ["content_item_id", "chunk_index"]},
        ),
        migrations.CreateModel(
            name="RagMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.CharField(choices=[("user", "用户"), ("assistant", "助手")], max_length=20)),
                ("content", models.TextField()),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("model", models.CharField(blank=True, max_length=80)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="agent_runtime.ragsession")),
            ],
            options={"verbose_name": "RAG消息", "verbose_name_plural": "RAG消息", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="LLMUsageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(max_length=40)),
                ("model", models.CharField(max_length=80)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("budget_remaining_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("status", models.CharField(choices=[("estimated", "估算"), ("final", "最终"), ("blocked", "预算拦截"), ("fallback", "兜底")], default="estimated", max_length=20)),
                ("message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usage_events", to="agent_runtime.ragmessage")),
                ("session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="usage_events", to="agent_runtime.ragsession")),
            ],
            options={"verbose_name": "LLM用量事件", "verbose_name_plural": "LLM用量事件", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RagCitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=300)),
                ("source_name", models.CharField(blank=True, max_length=160)),
                ("url", models.URLField(max_length=500)),
                ("snippet", models.TextField(blank=True)),
                ("content_item", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="aggregator.contentitem")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="citations", to="agent_runtime.ragmessage")),
            ],
            options={"verbose_name": "RAG引用", "verbose_name_plural": "RAG引用", "ordering": ["created_at"]},
        ),
        migrations.AddConstraint(
            model_name="contentchunk",
            constraint=models.UniqueConstraint(fields=("content_item", "chunk_index"), name="unique_rag_chunk_index"),
        ),
    ]
