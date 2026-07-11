from django.core.management.base import BaseCommand

from agent_runtime.services import rebuild_rag_chunks


class Command(BaseCommand):
    help = "Rebuild RAG content chunks and optionally sync them to Meilisearch."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--no-meili", action="store_true")

    def handle(self, *args, **options):
        result = rebuild_rag_chunks(limit=options["limit"], sync_meili=not options["no_meili"])
        self.stdout.write(self.style.SUCCESS(str(result)))
