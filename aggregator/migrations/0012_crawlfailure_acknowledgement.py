from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0010_source_source_group"),
        ("agent_runtime", "0011_agentrun_request_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlfailure",
            name="acknowledged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="acknowledged_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="acknowledged_status",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crawlfailure",
            name="http_status",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="crawlfailure",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        acknowledged_at__isnull=True,
                        acknowledged_status__isnull=True,
                        acknowledged_note="",
                    )
                    | (
                        models.Q(
                            acknowledged_at__isnull=False,
                            http_status__isnull=False,
                            http_status__in=[404, 410],
                            acknowledged_status__isnull=False,
                            acknowledged_status__in=[404, 410],
                            acknowledged_note__isnull=False,
                            failure_class="permanent",
                            permanent=True,
                        )
                        & models.Q(http_status=models.F("acknowledged_status"))
                        & ~models.Q(acknowledged_note="")
                    )
                ),
                name="crawlfailure_acknowledgement_valid",
            ),
        ),
    ]
