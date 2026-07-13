from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_runtime", "0010_evaluationrun_comparison_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="request_id",
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
    ]
