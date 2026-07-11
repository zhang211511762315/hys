from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run a local MCP server exposing safe site tools."

    def handle(self, *args, **options):
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError as exc:
            raise CommandError("mcp package is not installed. Rebuild the environment from requirements.txt.") from exc

        from aggregator.models import AIUsageDaily, ContentItem, CrawlFailure
        from agent_runtime.services import retrieve_contexts, run_self_heal

        mcp = FastMCP("zhongbei-info-agent")

        @mcp.tool()
        def search_public_content(query: str, limit: int = 5) -> list[dict]:
            contexts = retrieve_contexts(query, limit=max(1, min(limit, 10)))
            return [
                {
                    "title": context.item.title,
                    "source": context.item.source.name,
                    "url": context.item.canonical_url,
                    "snippet": context.text[:300],
                }
                for context in contexts
            ]

        @mcp.tool()
        def site_health() -> dict:
            return {
                "published_items": ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).count(),
                "open_failures": CrawlFailure.objects.filter(resolved_at__isnull=True).count(),
                "ai_usage_days": AIUsageDaily.objects.count(),
            }

        @mcp.tool()
        def self_heal_dry_run() -> dict:
            return run_self_heal(dry_run=True)

        self.stdout.write(
            self.style.WARNING(
                f"Starting local MCP server on stdio. Bind policy host={settings.MCP_BIND_HOST}; write tools are dry-run only."
            )
        )
        mcp.run()
