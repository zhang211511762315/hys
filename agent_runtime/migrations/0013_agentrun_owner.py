from django.db import migrations, models
from agent_runtime.online_migrations import OnlineNullableField


class Migration(migrations.Migration):
    dependencies = [
        ('agent_runtime', '0012_researchadmissionkey'),
    ]
    operations = [OnlineNullableField(model_name='agentrun', name='dispatch_meta',
                                     field=models.JSONField(default=dict, blank=True, null=True))]
