from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("agent_runtime", "0007_toolinvocation_attempt_traces")]

    operations = [
        migrations.AddField(
            model_name="contentchunk",
            name="embedding_fingerprint",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="contentchunk",
            name="embedding_version",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
