import httpx
from django.db.models import Q
from django.db import IntegrityError, transaction
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from aggregator.models import Attachment, Category, ContentItem, ContentSource, CrawlFailure, CrawlJob, DuplicateGroup, RawDocument, Source, Tag

from .ai import get_ai_provider
from .dedupe import content_fingerprint, is_near_duplicate, title_fingerprint
from .discovery import discover_article_links, discover_listing_links
from .employment import fetch_employment_documents, is_employment_source_url
from .extraction import ExtractedDocument, ExtractionError, fetch_and_extract
from .gate import evaluate_candidate
from .importance import score_importance
from .ocr import ocr_image_url
from .search import sync_item_to_search


def ingest_source(source: Source, crawl_job: CrawlJob | None = None) -> int:
    if is_employment_source_url(source.url):
        return _ingest_employment_source(source, crawl_job)

    if getattr(source, "source_type", "") in {
        Source.SourceType.SOCIAL_LINK,
        Source.SourceType.WECHAT_LINK,
        Source.SourceType.MANUAL_URL,
    }:
        try:
            ingest_url(source, source.url, crawl_job)
        except Exception as exc:
            _record_crawl_failure(crawl_job, source, source.url, exc)
            raise
        _mark_crawl_failure_resolved(source, source.url)
        _record_job_stat(crawl_job, "success_count")
        return 1

    max_articles = getattr(source, "max_articles_per_run", settings.CRAWL_MAX_LINKS_PER_SOURCE)
    max_list_pages = getattr(source, "max_list_pages_per_run", settings.CRAWL_MAX_LIST_PAGES_PER_SOURCE)
    crawl_depth = getattr(source, "crawl_depth", settings.CRAWL_DEFAULT_DEPTH)
    failed_retry_urls = _failed_retry_urls(source)
    article_urls = _discover_source_article_urls(source, max_articles, max_list_pages, crawl_depth, crawl_job)
    _set_job_stat(crawl_job, "discovered_count", len(article_urls))
    queued_urls = [*failed_retry_urls, *(url for url in article_urls if url not in set(failed_retry_urls))]
    if not queued_urls:
        _append_job_warning(crawl_job, "No article URLs discovered; attempted source URL fallback.")
        try:
            ingest_url(source, source.url, crawl_job)
        except Exception as exc:
            _record_crawl_failure(crawl_job, source, source.url, exc)
            raise
        _mark_crawl_failure_resolved(source, source.url)
        _record_job_stat(crawl_job, "success_count")
        return 1

    count = 0
    for article_url in queued_urls:
        try:
            ingest_url(source, article_url, crawl_job)
        except Exception as exc:
            _record_crawl_failure(crawl_job, source, article_url, exc)
            continue
        else:
            _mark_crawl_failure_resolved(source, article_url)
            _record_job_stat(crawl_job, "success_count")
            count += 1
    return count


def _ingest_employment_source(source: Source, crawl_job: CrawlJob | None = None) -> int:
    max_articles = getattr(source, "max_articles_per_run", settings.CRAWL_MAX_LINKS_PER_SOURCE)
    documents, fetches, failures = fetch_employment_documents(source.url, max_articles)
    for result in fetches:
        _record_fetch_via(crawl_job, result)
        _record_job_stat(crawl_job, "listing_pages_count")
    for failure in failures:
        _record_crawl_failure(crawl_job, source, failure.url, failure.exc)
    if failures:
        _append_job_warning(crawl_job, f"Employment API had {len(failures)} failed endpoint(s); ingested available notices.")
    if not documents and failures:
        raise failures[0].exc
    _set_job_stat(crawl_job, "discovered_count", len(documents))
    count = 0
    for document in documents:
        try:
            ingest_extracted_document(source, document, crawl_job)
        except Exception as exc:
            _record_crawl_failure(crawl_job, source, document.final_url or document.url, exc)
            continue
        _mark_crawl_failure_resolved(source, document.final_url or document.url)
        _record_job_stat(crawl_job, "success_count")
        count += 1
    return count


def _discover_source_article_urls(
    source: Source,
    max_articles: int,
    max_list_pages: int,
    crawl_depth: int,
    crawl_job: CrawlJob | None = None,
) -> list[str]:
    start_url = source.url
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
        except Exception as exc:
            _record_crawl_failure(crawl_job, source, page_url, exc)
            continue
        _record_fetch_via(crawl_job, document)
        _record_job_stat(crawl_job, "listing_pages_count")
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
    _record_fetch_via(crawl_job, document)
    item = ingest_extracted_document(source, document, crawl_job)
    _mark_crawl_failure_resolved(source, url)
    if document.final_url and document.final_url != url:
        _mark_crawl_failure_resolved(source, document.final_url)
    return item


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
    existing_item = ContentItem.objects.filter(content_hash=content_hash).order_by("id").first()
    if existing_item is not None and _has_complete_analysis(existing_item):
        _ensure_title_fingerprint(existing_item)
        _record_job_stat(crawl_job, "duplicate_skip_count")
        _record_job_stat(crawl_job, "ai_skip_count")
        _link_document_to_item(source, existing_item, raw_document, document, crawl_job)
        if existing_item.is_public:
            sync_item_to_search(existing_item)
        _queue_rag_index(existing_item.id)
        return existing_item

    near_duplicate = _find_near_duplicate_item(document)
    if near_duplicate is not None:
        _record_job_stat(crawl_job, "duplicate_skip_count")
        _record_job_stat(crawl_job, "near_duplicate_skip_count")
        _record_job_stat(crawl_job, "ai_skip_count")
        _link_document_to_item(source, near_duplicate, raw_document, document, crawl_job)
        _link_duplicate_group(near_duplicate)
        if near_duplicate.is_public:
            sync_item_to_search(near_duplicate)
        _queue_rag_index(near_duplicate.id)
        return near_duplicate

    combined_text = _combine_ocr_text(document.text, document.image_urls, source)
    analysis = get_ai_provider().analyze(combined_text, Category.objects.values_list("name", flat=True))
    if analysis.provider == "deepseek":
        _record_job_stat(crawl_job, "ai_call_count")
    elif getattr(settings, "AI_PROVIDER", "rules").lower() != "rules":
        _record_job_stat(crawl_job, "ai_fallback_count")
        _append_job_warning(crawl_job, "AI provider fell back to rules; budget may be exhausted or provider unavailable.")
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
            fetch_via=getattr(document, "fetch_via", "direct"),
            status_code=getattr(document, "status_code", 200),
        ),
    )
    with transaction.atomic():
        category = _get_or_create_category(analysis.category)
        item, created = _create_or_update_item(
            source,
            raw_document,
            document,
            combined_text,
            content_hash,
            analysis,
            category,
            decision,
        )
        _record_job_stat(crawl_job, "new_count" if created else "updated_count")
        _link_document_to_item(source, item, raw_document, document, crawl_job)
        for tag_name in analysis.tags:
            tag = _get_or_create_tag(tag_name)
            item.tags.add(tag)
    if item.is_public:
        sync_item_to_search(item)
    _queue_rag_index(item.id)
    return item


def _queue_rag_index(item_id: int) -> None:
    from agent_runtime.tasks import index_content_item_rag

    transaction.on_commit(lambda: index_content_item_rag.delay(item_id))


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


def _get_or_create_category(name: str) -> Category:
    category = Category.objects.filter(name=name).first()
    if category is not None:
        return category
    return Category.objects.create(name=name, slug=_unique_slug(Category, name, "category"))


def _get_or_create_tag(name: str) -> Tag:
    tag = Tag.objects.filter(name=name).first()
    if tag is not None:
        return tag
    return Tag.objects.create(name=name, slug=_unique_slug(Tag, name, "tag"))


def _unique_slug(model, name: str, prefix: str) -> str:
    base = slugify(name) or f"{prefix}-{content_fingerprint(name)[:8]}"
    base = base[:70]
    slug = base
    counter = 2
    while model.objects.filter(slug=slug).exists():
        slug = f"{base[:60]}-{content_fingerprint(name)[:6]}-{counter}"
        counter += 1
    return slug


def _create_or_update_item(source, raw_document, document, combined_text, content_hash, analysis, category, decision):
    item = ContentItem.objects.filter(content_hash=content_hash).order_by("id").first()
    defaults = {
        "source": source,
        "raw_document": raw_document,
        "title": document.title or document.final_url,
        "title_fingerprint": title_fingerprint(document.title or document.final_url),
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
        return item, False
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
    return item, created


def _has_complete_analysis(item: ContentItem) -> bool:
    return bool(item.summary and item.category_id and item.ai_provider)


def _ensure_title_fingerprint(item: ContentItem) -> None:
    if item.title_fingerprint:
        return
    item.title_fingerprint = title_fingerprint(item.title)
    item.save(update_fields=["title_fingerprint", "updated_at"])


def _find_near_duplicate_item(document: ExtractedDocument) -> ContentItem | None:
    fingerprint = title_fingerprint(document.title or document.final_url)
    if len(fingerprint) < 8:
        return None
    threshold = getattr(settings, "CRAWL_NEAR_DUPLICATE_TEXT_THRESHOLD", 0.88)
    candidates = ContentItem.objects.filter(title_fingerprint=fingerprint).exclude(content_text="").order_by("id")[:10]
    for item in candidates:
        if not _has_complete_analysis(item):
            continue
        if is_near_duplicate(document.text, item.content_text, threshold=threshold):
            return item
    return None


def _link_duplicate_group(item: ContentItem) -> None:
    if item.duplicate_group_id:
        return
    group, _ = DuplicateGroup.objects.get_or_create(
        fingerprint=f"title:{item.title_fingerprint or title_fingerprint(item.title)}",
        defaults={"canonical_item": item},
    )
    item.duplicate_group = group
    item.save(update_fields=["duplicate_group", "updated_at"])


def _link_document_to_item(
    source: Source,
    item: ContentItem,
    raw_document: RawDocument,
    document: ExtractedDocument,
    crawl_job: CrawlJob | None = None,
) -> None:
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
    max_source_url_length = Attachment._meta.get_field("source_url").max_length
    for image_url in document.image_urls[:10]:
        if len(image_url) > max_source_url_length:
            _append_job_warning(crawl_job, "An attachment URL exceeded the supported length and was skipped.")
            continue
        Attachment.objects.get_or_create(content_item=item, source_url=image_url)


def _record_job_stat(crawl_job: CrawlJob | None, field: str, amount: int = 1) -> None:
    if crawl_job is None:
        return
    setattr(crawl_job, field, getattr(crawl_job, field) + amount)
    crawl_job.save(update_fields=[field, "updated_at"])


def _set_job_stat(crawl_job: CrawlJob | None, field: str, value: int) -> None:
    if crawl_job is None:
        return
    setattr(crawl_job, field, value)
    crawl_job.save(update_fields=[field, "updated_at"])


def _append_job_warning(crawl_job: CrawlJob | None, message: str) -> None:
    if crawl_job is None:
        return
    crawl_job.warning_message = "\n".join(part for part in [crawl_job.warning_message, message] if part)
    crawl_job.save(update_fields=["warning_message", "updated_at"])


def _record_fetch_via(crawl_job: CrawlJob | None, document) -> None:
    via = getattr(document, "fetch_via", getattr(document, "via", "direct"))
    if via == "relay":
        _record_job_stat(crawl_job, "relay_fetch_count")
    else:
        _record_job_stat(crawl_job, "direct_fetch_count")


def _failed_retry_urls(source: Source) -> list[str]:
    if not getattr(source, "pk", None):
        return []
    limit = getattr(settings, "CRAWL_RETRY_FAILED_URLS_PER_RUN", 10)
    if limit <= 0:
        return []
    urls = []
    seen = set()
    failures = (
        CrawlFailure.objects.filter(source=source, resolved_at__isnull=True, permanent=False)
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now()))
        .order_by("-created_at")
        .values_list("url", flat=True)
    )
    for url in failures:
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _mark_crawl_failure_resolved(source: Source, url: str) -> None:
    if not getattr(source, "pk", None):
        return
    CrawlFailure.objects.filter(source=source, url=url, resolved_at__isnull=True).update(resolved_at=timezone.now())


def _record_crawl_failure(crawl_job: CrawlJob | None, source: Source, url: str, exc: Exception) -> None:
    if crawl_job is not None:
        failure_class, permanent, http_status = _classify_failure(exc)
        last_failure = (
            CrawlFailure.objects.filter(source=source, url=url, resolved_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        retry_count = (last_failure.retry_count + 1) if last_failure else 0
        next_retry_at = None
        if not permanent:
            minutes = min(
                getattr(settings, "CRAWL_FAILURE_RETRY_MAX_MINUTES", 1440),
                getattr(settings, "CRAWL_FAILURE_RETRY_BASE_MINUTES", 30) * (2 ** retry_count),
            )
            next_retry_at = timezone.now() + timezone.timedelta(minutes=minutes)
        failure_defaults = {
            "crawl_job": crawl_job,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:2000],
            "failure_class": failure_class,
            "retry_count": retry_count,
            "next_retry_at": next_retry_at,
            "permanent": permanent,
            "http_status": http_status,
            "acknowledged_at": None,
            "acknowledged_status": None,
            "acknowledged_note": "",
        }
        if last_failure is not None:
            CrawlFailure.objects.filter(source=source, url=url, resolved_at__isnull=True).exclude(
                id=last_failure.id
            ).update(resolved_at=timezone.now())
            for field, value in failure_defaults.items():
                setattr(last_failure, field, value)
            last_failure.save(update_fields=[*failure_defaults, "updated_at"])
        else:
            CrawlFailure.objects.create(
                source=source,
                url=url,
                **failure_defaults,
            )
        _record_job_stat(crawl_job, "failed_url_count")


def _classify_failure(exc: Exception) -> tuple[str, bool, int | None]:
    message = str(exc).lower()
    if isinstance(exc, ExtractionError) and ("missing or expired" in message or "不存在" in message or "过期" in message):
        return CrawlFailure.FailureClass.PERMANENT, True, None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {404, 410}:
        return CrawlFailure.FailureClass.PERMANENT, True, exc.response.status_code
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException)):
        return CrawlFailure.FailureClass.NETWORK, False, None
    if "network is unreachable" in message or "timed out" in message:
        return CrawlFailure.FailureClass.NETWORK, False, None
    return CrawlFailure.FailureClass.TRANSIENT, False, None
