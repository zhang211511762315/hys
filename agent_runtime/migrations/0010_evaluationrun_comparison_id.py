from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_runtime", "0009_evaluationrun_evaluationcaseresult"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationrun",
            name="comparison_id",
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
    ]
