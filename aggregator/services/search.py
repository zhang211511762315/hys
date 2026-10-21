import logging
import json

from django.conf import settings

logger = logging.getLogger(__name__)


def sync_item_to_search(item):
    if not settings.MEILISEARCH_URL:
        return
    try:
        import meilisearch
    except ImportError:
        logger.warning("meilisearch package not installed")
        return
    try:
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        index = client.index(settings.MEILISEARCH_INDEX)
        doc = search_document(item)
        index.add_documents([doc])
    except Exception as e:
        logger.error("Failed to sync item %s to Meilisearch: %s", item.id, e)


def search_items(query: str, filters: dict | None = None):
    if not settings.MEILISEARCH_URL:
        return []
    try:
        import meilisearch
    except ImportError:
        logger.warning("meilisearch package not installed, falling back")
        return []
    try:
        client = meilisearch.Client(settings.MEILISEARCH_URL, settings.MEILISEARCH_MASTER_KEY or None)
        options = {"limit": 1000}
        if filters:
            filter_parts = []
            if filters.get("category_slug"):
                filter_parts.append("category_slug = " + json.dumps(filters["category_slug"]))
            for key, operator in (("published_from", ">="), ("published_to", "<=")):
                if filters.get(key) is not None:
                    filter_parts.append(f"source_published_at_ts {operator} {int(filters[key])}")
            if filter_parts:
                options["filter"] = " AND ".join(filter_parts)
        result = client.index(settings.MEILISEARCH_INDEX).search(query, options)
        return result.get("hits", [])
    except Exception as e:
        logger.error("Meilisearch search failed: %s", e)
        return []


def search_document(item):
    return {
        "id": item.id,
        "title": item.title,
        "summary": item.summary,
        "content": item.content_text,
        "source": item.source.name,
        "source_type": item.source.source_type,
        "category": item.category.name if item.category else "",
        "category_slug": item.category.slug if item.category else "",
        "source_published_at_ts": int(item.source_published_at.timestamp()) if item.source_published_at else 0,
        "url": item.canonical_url,
        "published_at": item.source_published_at.isoformat()
        if item.source_published_at
        else item.published_at.isoformat()
        if item.published_at
        else "",
    }
