"""Explicit, bounded index preparation; never invoked by application startup."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from aggregator.models import ContentItem
from aggregator.services.search import search_document


class Command(BaseCommand):
    help = "Prepare category/date filters and refresh public search documents."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not options['apply']:
            self.stdout.write('Read-only: pass --apply to prepare the configured search index.')
            return
        if not settings.MEILISEARCH_URL:
            raise CommandError('search index is not configured')
        import meilisearch
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        index = client.index(settings.MEILISEARCH_INDEX)

        def wait(task):
            uid = task.get('taskUid') if isinstance(task, dict) else task.task_uid
            finished = client.wait_for_task(uid, timeout_in_ms=60000)
            status = finished.get('status') if isinstance(finished, dict) else finished.status
            if status != 'succeeded':
                raise CommandError('search indexing task did not succeed')

        existing = index.get_filterable_attributes()
        wait(index.update_filterable_attributes(list(dict.fromkeys([*existing, 'category_slug', 'source_published_at_ts']))))
        items = ContentItem.objects.filter(status='published', is_public=True,
            source_published_at__lte=timezone.now()).select_related('source', 'category').order_by('pk')
        count = 0
        batch = []
        for item in items.iterator(chunk_size=50):
            batch.append(search_document(item))
            if len(batch) == 50:
                wait(index.add_documents(batch))
                count += len(batch)
                batch = []
        if batch:
            wait(index.add_documents(batch))
            count += len(batch)
        self.stdout.write(f'Indexed {count} public documents with category/date filters.')
