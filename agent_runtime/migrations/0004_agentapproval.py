import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("agent_runtime", "0003_research_runtime"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("tool_name", models.CharField(max_length=80)),
                ("tool_version", models.CharField(default="1", max_length=40)),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("result_json", models.JSONField(blank=True, default=dict)),
                ("idempotency_key", models.CharField(max_length=160, unique=True)),
                ("status", models.CharField(choices=[("pending", "待审批"), ("executing", "执行中"), ("executed", "已执行"), ("rejected", "已拒绝"), ("failed", "失败")], default="pending", max_length=20)),
                ("error_message", models.TextField(blank=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="agent_approval_decisions", to=settings.AUTH_USER_MODEL)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="approvals", to="agent_runtime.agentrun")),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
