from django.db import IntegrityError, transaction
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from aggregator.models import Attachment, Category, ContentItem, ContentSource, CrawlJob, RawDocument, Source, Tag

from .ai import get_ai_provider
from .dedupe import content_fingerprint
from .discovery import discover_article_links, discover_listing_links
from .extraction import ExtractedDocument, fetch_and_extract
from .gate import evaluate_candidate
from .importance import score_importance
from .ocr import ocr_image_url
from .search import sync_item_to_search


def ingest_source(source: Source, crawl_job: CrawlJob | None = None) -> int:
    if getattr(source, "source_type", "") in {
        Source.SourceType.SOCIAL_LINK,
        Source.SourceType.WECHAT_LINK,
        Source.SourceType.MANUAL_URL,
    }:
        ingest_url(source, source.url, crawl_job)
        return 1

    max_articles = getattr(source, "max_articles_per_run", settings.CRAWL_MAX_LINKS_PER_SOURCE)
    max_list_pages = getattr(source, "max_list_pages_per_run", settings.CRAWL_MAX_LIST_PAGES_PER_SOURCE)
    crawl_depth = getattr(source, "crawl_depth", settings.CRAWL_DEFAULT_DEPTH)
    article_urls = _discover_source_article_urls(source.url, max_articles, max_list_pages, crawl_depth)
    if not article_urls:
        ingest_url(source, source.url, crawl_job)
        return 1

    count = 0
    for article_url in article_urls:
        try:
            ingest_url(source, article_url, crawl_job)
        except Exception:
            continue
        else:
            count += 1
    return count


def _discover_source_article_urls(start_url: str, max_articles: int, max_list_pages: int, crawl_depth: int) -> list[str]:
    queue = [(start_url, 1)]
    visited_pages = set()
    article_urls: list[str] = []
    seen_articles = set()

    while queue and len(visited_pages) < max_list_pages and len(article_urls) < max_articles:
        page_url, depth = queue.pop(0)
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)
        try:
            document = fetch_and_extract(page_url)
        except Exception:
            continue
        for article_url in discover_article_links(document.html, page_url, max_links=max_articles):
            if article_url in seen_articles:
                continue
            seen_articles.add(article_url)
            article_urls.append(article_url)
            if len(article_urls) >= max_articles:
                break
        if depth >= crawl_depth:
            continue
        for listing_url in discover_listing_links(document.html, page_url, max_links=max_list_pages):
            if listing_url not in visited_pages:
                queue.append((listing_url, depth + 1))

    return article_urls


def ingest_url(source: Source, url: str, crawl_job: CrawlJob | None = None) -> ContentItem:
    document = fetch_and_extract(url)
    return ingest_extracted_document(source, document, crawl_job)


def ingest_extracted_document(
    source: Source,
    document: ExtractedDocument,
    crawl_job: CrawlJob | None = None,
) -> ContentItem:
    content_hash = content_fingerprint(document.text)
    raw_document, _ = RawDocument.objects.get_or_create(
        source=source,
        content_hash=content_hash,
        defaults={
            "crawl_job": crawl_job,
            "url": document.url,
            "final_url": document.final_url,
            "title": document.title,
            "html": document.html,
            "extracted_text": document.text,
        },
    )
    combined_text = _combine_ocr_text(document.text, document.image_urls, source)
    analysis = get_ai_provider().analyze(combined_text, Category.objects.values_list("name", flat=True))
    decision = evaluate_candidate(
        source,
        ExtractedDocument(
            url=document.url,
            final_url=document.final_url,
            title=document.title,
            html=document.html,
            text=combined_text,
            image_urls=document.image_urls,
            published_at=document.published_at,
            date_confidence=getattr(document, "date_confidence", "exact"),
        ),
    )
    with transaction.atomic():
        category, _ = Category.objects.get_or_create(
            name=analysis.category,
            defaults={"slug": slugify(analysis.category) or f"category-{Category.objects.count() + 1}"},
        )
        item = _create_or_update_item(
            source,
            raw_document,
            document,
            combined_text,
            content_hash,
            analysis,
            category,
            decision,
        )
        ContentSource.objects.update_or_create(
            content_item=item,
            source=source,
            url=document.final_url or document.url,
            defaults={
                "raw_document": raw_document,
                "source_title": document.title,
                "source_published_at": document.published_at,
            },
        )
        for image_url in document.image_urls[:10]:
            Attachment.objects.get_or_create(content_item=item, source_url=image_url)
        for tag_name in analysis.tags:
            tag, _ = Tag.objects.get_or_create(
                name=tag_name,
                defaults={"slug": slugify(tag_name) or f"tag-{Tag.objects.count() + 1}"},
            )
            item.tags.add(tag)
    if item.is_public:
        sync_item_to_search(item)
    return item


def _combine_ocr_text(text: str, image_urls: list[str], source: Source | None = None) -> str:
    if len((text or "").strip()) >= settings.OCR_MIN_TEXT_LENGTH:
        return text.strip()
    if source is not None and not _should_run_ocr_for_source(source):
        return (text or "").strip()
    ocr_chunks = []
    for image_url in image_urls[: settings.OCR_MAX_IMAGES_PER_PAGE]:
        try:
            result = ocr_image_url(image_url)
        except Exception:
            continue
        if result.text:
            ocr_chunks.append(result.text)
    return "\n".join([text, *ocr_chunks]).strip()


def _should_run_ocr_for_source(source: Source) -> bool:
    if source.source_type in {Source.SourceType.SOCIAL_LINK, Source.SourceType.WECHAT_LINK, Source.SourceType.MANUAL_URL}:
        return True
    return settings.OCR_ENABLE_FOR_WEB


def _create_or_update_item(source, raw_document, document, combined_text, content_hash, analysis, category, decision):
    item = ContentItem.objects.filter(content_hash=content_hash).order_by("id").first()
    defaults = {
        "source": source,
        "raw_document": raw_document,
        "title": document.title or document.final_url,
        "summary": analysis.summary,
        "content_text": combined_text,
        "content_hash": content_hash,
        "importance_score": score_importance(source, document.title or "", combined_text, category.name, document.published_at),
        "review_status": decision.review_status,
        "date_confidence": decision.date_confidence,
        "extraction_quality_score": decision.extraction_quality_score,
        "is_public": decision.is_public,
        "review_reason": decision.review_reason,
        "ai_provider": analysis.provider,
        "category": category,
        "status": ContentItem.Status.PUBLISHED if decision.is_public else ContentItem.Status.CLEANED,
        "published_at": timezone.now(),
        "source_published_at": document.published_at,
    }
    if item is not None:
        mutable_defaults = defaults.copy()
        mutable_defaults.pop("source")
        mutable_defaults.pop("canonical_url", None)
        if item.canonical_url == (document.final_url or document.url):
            mutable_defaults["source"] = source
        if not item.is_public and decision.is_public:
            mutable_defaults["review_status"] = decision.review_status
            mutable_defaults["is_public"] = decision.is_public
            mutable_defaults["status"] = ContentItem.Status.PUBLISHED
        for field, value in mutable_defaults.items():
            setattr(item, field, value)
        item.save()
        return item
    try:
        item, created = ContentItem.objects.update_or_create(
            canonical_url=document.final_url or document.url,
            defaults=defaults,
        )
    except IntegrityError:
        item = ContentItem.objects.get(canonical_url=document.final_url or document.url)
        created = False
    if not created:
        for field, value in defaults.items():
            setattr(item, field, value)
        item.save()
    return item
