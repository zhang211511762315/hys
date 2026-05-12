from django.conf import settings


def sync_item_to_search(item):
    if not settings.MEILISEARCH_URL:
        return
    try:
        import meilisearch
    except ImportError:
        return
    try:
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        index = client.index(settings.MEILISEARCH_INDEX)
        index.add_documents(
            [
                {
                    "id": item.id,
                    "title": item.title,
                    "summary": item.summary,
                    "content": item.content_text,
                    "source": item.source.name,
                    "source_type": item.source.source_type,
                    "category": item.category.name if item.category else "",
                    "url": item.canonical_url,
                    "published_at": item.published_at.isoformat() if item.published_at else "",
                }
            ]
        )
    except Exception:
        return


def search_items(query: str, filters: dict | None = None):
    try:
        import meilisearch
    except ImportError:
        return []
    try:
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        options = {"limit": 30}
        if filters:
            filter_parts = [f'{key} = "{value}"' for key, value in filters.items() if value]
            if filter_parts:
                options["filter"] = " AND ".join(filter_parts)
        result = client.index(settings.MEILISEARCH_INDEX).search(query, options)
        return result.get("hits", [])
    except Exception:
        return []
