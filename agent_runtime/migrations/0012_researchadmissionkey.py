from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_runtime", "0011_agentrun_request_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchAdmissionKey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client_request_id", models.CharField(max_length=120, unique=True)),
            ],
            options={
                "verbose_name": "研究请求准入键",
                "verbose_name_plural": "研究请求准入键",
            },
        ),
    ]
