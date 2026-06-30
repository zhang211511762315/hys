import socket
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from aggregator.models import Source


class Command(BaseCommand):
    help = "Check source DNS/HTTP health and optionally disable unreachable sources."

    def add_arguments(self, parser):
        parser.add_argument("--disable-dead", action="store_true", help="Disable sources that fail DNS resolution.")
        parser.add_argument(
            "--include-disabled",
            action="store_true",
            help="Also check sources whose crawl_enabled flag is disabled.",
        )
        parser.add_argument("--timeout", type=float, default=8.0)

    def handle(self, *args, **options):
        timeout = options["timeout"]
        disable_dead = options["disable_dead"]
        include_disabled = options["include_disabled"]
        checked = 0
        failed = 0
        disabled = 0

        sources = Source.objects.filter(enabled=True)
        if not include_disabled:
            sources = sources.filter(crawl_enabled=True)

        for source in sources.order_by("priority", "id"):
            checked += 1
            host = urlsplit(source.url).hostname or ""
            dns_error = ""
            http_status = ""
            error = ""
            try:
                socket.getaddrinfo(host, None)
            except OSError as exc:
                dns_error = str(exc)
                error = f"DNS failed: {dns_error}"
            if not error:
                try:
                    response = httpx.head(
                        source.url,
                        headers={"User-Agent": settings.CRAWL_USER_AGENT},
                        follow_redirects=True,
                        timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
                    )
                    http_status = str(response.status_code)
                    if response.status_code >= 500:
                        error = f"HTTP {response.status_code}"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"

            if error:
                failed += 1
                if disable_dead and dns_error and source.crawl_enabled:
                    note = f"Auto-disabled by check_sources at {timezone.localtime():%Y-%m-%d %H:%M}: {error}"
                    source.crawl_enabled = False
                    source.notes = "\n".join(part for part in [source.notes, note] if part)
                    source.last_error_at = timezone.now()
                    source.save(update_fields=["crawl_enabled", "notes", "last_error_at", "updated_at"])
                    disabled += 1
                self.stdout.write(self.style.WARNING(f"FAIL #{source.id} {source.name} {source.url} {error}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"OK   #{source.id} {source.name} {source.url} HTTP {http_status}"))

        self.stdout.write(f"Checked {checked} source(s), failed {failed}, disabled {disabled}.")
