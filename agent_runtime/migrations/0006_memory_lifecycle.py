# Generated manually for production-safe additive memory lifecycle fields.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agent_runtime", "0005_agentrun_replay_of"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ragsession",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ragsession",
            name="user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="rag_sessions", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="MemoryEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("content", models.CharField(max_length=1000)),
                ("consented_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("source_session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="memory_entries", to="agent_runtime.ragsession")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memory_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "长期记忆", "verbose_name_plural": "长期记忆", "ordering": ["-created_at"]},
        ),
    ]
