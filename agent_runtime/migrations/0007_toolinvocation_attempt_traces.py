import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("agent_runtime", "0006_memory_lifecycle")]

    operations = [
        migrations.RemoveConstraint(
            model_name="toolinvocation",
            name="unique_agent_tool_step",
        ),
        migrations.AddField(
            model_name="toolinvocation",
            name="error_type",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddConstraint(
            model_name="toolinvocation",
            constraint=models.UniqueConstraint(fields=("run", "step_id", "attempt"), name="unique_agent_tool_step_attempt"),
        ),
    ]
