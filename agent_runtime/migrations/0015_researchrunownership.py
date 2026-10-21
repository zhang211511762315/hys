from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from agent_runtime.online_migrations import OnlineCreateModel


class Migration(migrations.Migration):
    dependencies = [
        ('agent_runtime', '0014_research_cancelling_state'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [OnlineCreateModel(
        name='ResearchRunOwnership',
        fields=[
            ('run', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                                        related_name='ownership', serialize=False, to='agent_runtime.agentrun')),
            ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                        related_name='research_run_ownerships', to=settings.AUTH_USER_MODEL)),
        ],
    )]
