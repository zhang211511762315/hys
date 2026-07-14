import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_runtime", "0008_contentchunk_embedding_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("dataset_version", models.CharField(max_length=80)),
                ("strategy", models.CharField(default="single_agent", max_length=80)),
                (
                    "mode",
                    models.CharField(
                        choices=[("offline", "零成本离线"), ("paid", "付费")],
                        default="offline",
                        max_length=20,
                    ),
                ),
                ("budget_cap_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                (
                    "status",
                    models.CharField(
                        choices=[("running", "运行中"), ("succeeded", "成功"), ("failed", "失败")],
                        default="running",
                        max_length=20,
                    ),
                ),
                ("metrics_json", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                (
                    "agent_run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="evaluation_run",
                        to="agent_runtime.agentrun",
                    ),
                ),
            ],
            options={
                "verbose_name": "评测运行",
                "verbose_name_plural": "评测运行",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="EvaluationCaseResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("case_id", models.CharField(editable=False, max_length=80)),
                ("category", models.CharField(editable=False, max_length=80)),
                ("goal", models.TextField(editable=False)),
                ("expected_task_type", models.CharField(editable=False, max_length=80)),
                ("expected_tools", models.JSONField(default=list, editable=False)),
                ("actual_task_type", models.CharField(blank=True, editable=False, max_length=80)),
                ("actual_tools", models.JSONField(default=list, editable=False)),
                ("status", models.CharField(choices=[("succeeded", "成功"), ("failed", "失败")], max_length=20)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("cost_cny", models.DecimalField(decimal_places=6, default=Decimal("0"), max_digits=10)),
                ("detail_json", models.JSONField(blank=True, default=dict)),
                (
                    "evaluation_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="case_results",
                        to="agent_runtime.evaluationrun",
                    ),
                ),
            ],
            options={
                "verbose_name": "评测用例结果",
                "verbose_name_plural": "评测用例结果",
                "ordering": ["case_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("evaluation_run", "case_id"),
                        name="unique_evaluation_case_result",
                    )
                ],
            },
        ),
    ]
