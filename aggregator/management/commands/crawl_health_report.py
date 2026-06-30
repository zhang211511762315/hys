from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure, CrawlJob, CrawlNetworkEvent, Source


class Command(BaseCommand):
    help = "Print recent crawl health, source failures, date anomalies, and AI usage."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **options):
        since = timezone.now() - timezone.timedelta(hours=options["hours"])
        self.stdout.write(f"Crawl health since {timezone.localtime(since):%Y-%m-%d %H:%M:%S %Z}")

        jobs = CrawlJob.objects.filter(created_at__gte=since)
        self.stdout.write(f"Jobs: {jobs.count()} total")
        for row in jobs.values("status").annotate(n=Count("id")).order_by("status"):
            self.stdout.write(f"  {row['status']}: {row['n']}")
        fetch_totals = jobs.aggregate(
            direct=Sum("direct_fetch_count"),
            relay=Sum("relay_fetch_count"),
            near_duplicates=Sum("near_duplicate_skip_count"),
            ai_calls=Sum("ai_call_count"),
            ai_skips=Sum("ai_skip_count"),
        )
        self.stdout.write(f"Fetches: direct={fetch_totals['direct'] or 0} relay={fetch_totals['relay'] or 0}")
        self.stdout.write(
            f"AI: calls={fetch_totals['ai_calls'] or 0} skips={fetch_totals['ai_skips'] or 0} "
            f"near_duplicate_skips={fetch_totals['near_duplicates'] or 0}"
        )

        latest_job = CrawlJob.objects.aggregate(latest=Max("finished_at"))["latest"]
        if latest_job:
            self.stdout.write(f"Latest finished job: {timezone.localtime(latest_job):%Y-%m-%d %H:%M:%S %Z}")
        open_jobs = CrawlJob.objects.filter(status__in=[CrawlJob.Status.QUEUED, CrawlJob.Status.RUNNING])
        oldest_open = open_jobs.aggregate(oldest=Min("created_at"))["oldest"]
        self.stdout.write(f"Open jobs: {open_jobs.count()} oldest={_fmt(oldest_open)}")

        failed_sources = Source.objects.filter(enabled=True, crawl_enabled=True, failure_count__gt=0).order_by(
            "-failure_count", "id"
        )
        self.stdout.write(f"Active problem sources: {failed_sources.count()}")
        for source in failed_sources[:20]:
            self.stdout.write(
                f"  #{source.id} {source.name} failures={source.failure_count} next={_fmt(source.next_crawl_at)}"
            )
        disabled_sources = Source.objects.filter(enabled=True, crawl_enabled=False).order_by("id")
        self.stdout.write(f"Disabled crawl sources: {disabled_sources.count()}")
        for source in disabled_sources[:20]:
            self.stdout.write(
                f"  #{source.id} {source.name} failures={source.failure_count} next={_fmt(source.next_crawl_at)}"
            )

        failures = CrawlFailure.objects.filter(Q(created_at__gte=since) | Q(updated_at__gte=since)).select_related(
            "source", "crawl_job"
        )
        unresolved_failures = failures.filter(resolved_at__isnull=True)
        self.stdout.write(f"Failed URLs: {failures.count()} total, {unresolved_failures.count()} unresolved")
        retryable_failures = unresolved_failures.filter(permanent=False)
        permanent_failures = unresolved_failures.filter(permanent=True)
        self.stdout.write(
            f"Active failed URLs: {retryable_failures.count()} retryable, {permanent_failures.count()} permanent"
        )
        for row in unresolved_failures.values("failure_class", "permanent").annotate(n=Count("id")).order_by("failure_class"):
            self.stdout.write(f"  {row['failure_class']} permanent={row['permanent']}: {row['n']}")
        for failure in retryable_failures[:20]:
            self.stdout.write(
                f"  job={failure.crawl_job_id} source=#{failure.source_id} "
                f"{failure.failure_class}/{failure.error_type} retry={failure.retry_count} "
                f"next={_fmt(failure.next_retry_at)}: {failure.url}"
            )

        network_events = CrawlNetworkEvent.objects.filter(created_at__gte=since)
        self.stdout.write(f"Network events: {network_events.count()}")
        for event in network_events[:10]:
            group = event.schedule_group or "due"
            self.stdout.write(
                f"  {timezone.localtime(event.created_at):%Y-%m-%d %H:%M} {group} "
                f"{event.reason} checked={event.checked_count} reachable={event.reachable_count}"
            )

        zero_discovery = jobs.filter(discovered_count=0, status=CrawlJob.Status.SUCCEEDED).exclude(warning_message="")
        self.stdout.write(f"Zero-discovery warning jobs: {zero_discovery.count()}")

        future_items = ContentItem.objects.filter(is_public=True, source_published_at__gt=timezone.now())
        self.stdout.write(f"Public items with future source date: {future_items.count()}")
        for item in future_items[:20]:
            self.stdout.write(f"  #{item.id} {item.source_published_at:%Y-%m-%d} {item.title[:80]}")

        usage = AIUsageDaily.objects.order_by("-usage_date").first()
        if usage:
            self.stdout.write(
                f"Latest AI usage: {usage.usage_date} {usage.provider}/{usage.model} "
                f"requests={usage.request_count} cost_cny={usage.cost_cny}"
            )


def _fmt(value):
    if not value:
        return "-"
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
