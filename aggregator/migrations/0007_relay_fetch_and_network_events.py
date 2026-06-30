from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aggregator", "0006_crawljob_stats_failures_and_cleanup"),
    ]

    operations = [
        migrations.AddField(
            model_name="crawljob",
            name="direct_fetch_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="crawljob",
            name="relay_fetch_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="CrawlNetworkEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("schedule_group", models.CharField(blank=True, max_length=40)),
                ("checked_count", models.PositiveIntegerField(default=0)),
                ("reachable_count", models.PositiveIntegerField(default=0)),
                ("reason", models.CharField(max_length=200)),
                ("probe_urls", models.JSONField(blank=True, default=list)),
            ],
            options={
                "verbose_name": "抓取网络事件",
                "verbose_name_plural": "抓取网络事件",
                "ordering": ["-created_at"],
            },
        ),
    ]
