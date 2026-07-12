import uuid

from django.db import migrations, models
import django.db.models.deletion


def populate_public_ids(apps, schema_editor):
    AgentRun = apps.get_model("agent_runtime", "AgentRun")
    for run in AgentRun.objects.filter(public_id__isnull=True).iterator():
        run.public_id = uuid.uuid4()
        run.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [("agent_runtime", "0002_agentrun_eval_kind")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="public_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(
            populate_public_ids,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="agentrun",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="client_request_id",
            field=models.CharField(blank=True, max_length=120, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="goal",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="state_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="current_node",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="graph_version",
            field=models.CharField(default="research-v1", max_length=40),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="prompt_version",
            field=models.CharField(default="research-v1", max_length=40),
        ),
        migrations.AlterField(
            model_name="agentrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "排队中"),
                    ("planning", "规划中"),
                    ("executing", "执行中"),
                    ("verifying", "验证中"),
                    ("waiting_approval", "等待审批"),
                    ("running", "运行中"),
                    ("succeeded", "成功"),
                    ("failed", "失败"),
                    ("cancelled", "已取消"),
                ],
                default="running",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="AgentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sequence", models.PositiveIntegerField()),
                ("event_type", models.CharField(max_length=80)),
                ("payload_json", models.JSONField(blank=True, default=dict)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="agent_runtime.agentrun")),
            ],
            options={"ordering": ["sequence"]},
        ),
        migrations.CreateModel(
            name="ToolInvocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("step_id", models.CharField(max_length=40)),
                ("tool_name", models.CharField(max_length=80)),
                ("tool_version", models.CharField(default="1", max_length=40)),
                ("risk_level", models.CharField(default="low", max_length=20)),
                ("permission", models.CharField(default="public", max_length=20)),
                ("status", models.CharField(choices=[("running", "运行中"), ("succeeded", "成功"), ("failed", "失败"), ("denied", "拒绝")], default="running", max_length=20)),
                ("attempt", models.PositiveIntegerField(default=1)),
                ("input_json", models.JSONField(blank=True, default=dict)),
                ("output_json", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("idempotency_key", models.CharField(blank=True, max_length=160)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tool_invocations", to="agent_runtime.agentrun")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddConstraint(
            model_name="agentevent",
            constraint=models.UniqueConstraint(fields=("run", "sequence"), name="unique_agent_event_sequence"),
        ),
        migrations.AddConstraint(
            model_name="toolinvocation",
            constraint=models.UniqueConstraint(fields=("run", "step_id"), name="unique_agent_tool_step"),
        ),
    ]
