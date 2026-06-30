from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0007_relay_fetch_and_network_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawlfailure",
            name="resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
