from dataclasses import dataclass, replace
from datetime import datetime
import json
from urllib.parse import urlencode, urljoin, urlsplit

from django.conf import settings
from django.utils import timezone

from .extraction import ExtractedDocument, extract_document_from_html
from .fetching import FetchResult, fetch_url
from .urls import normalize_url


@dataclass(frozen=True)
class EmploymentFetchFailure:
    url: str
    exc: Exception


class EmploymentAPIError(ValueError):
    pass


def is_employment_source_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == "zbjy.nuc.edu.cn"


def fetch_employment_documents(
    source_url: str,
    max_articles: int,
) -> tuple[list[ExtractedDocument], list[FetchResult], list[EmploymentFetchFailure]]:
    base_url = normalize_url(source_url)
    documents: list[ExtractedDocument] = []
    fetches: list[FetchResult] = []
    failures: list[EmploymentFetchFailure] = []
    seen = set()
    page_size = max(1, getattr(settings, "CRAWL_EMPLOYMENT_PAGE_SIZE", 15))
    type_ids = getattr(settings, "CRAWL_EMPLOYMENT_NOTICE_TYPE_IDS", [])

    for type_id in type_ids:
        page = 1
        while len(documents) < max_articles:
            endpoint = _employment_api_url(base_url, type_id, page, page_size)
            try:
                result = fetch_url(endpoint)
            except Exception as exc:
                failures.append(EmploymentFetchFailure(endpoint, exc))
                break
            fetches.append(result)
            try:
                payload = json.loads(result.text)
            except json.JSONDecodeError as exc:
                failures.append(EmploymentFetchFailure(endpoint, EmploymentAPIError(_invalid_payload_message(result.text))))
                break
            if not isinstance(payload, dict):
                failures.append(EmploymentFetchFailure(endpoint, EmploymentAPIError("employment API returned a non-object payload")))
                break
            rows = payload.get("data") or []
            if not isinstance(rows, list):
                failures.append(EmploymentFetchFailure(endpoint, EmploymentAPIError("employment API returned non-list data")))
                break
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                document = _document_from_notice(base_url, type_id, row)
                if not document or document.final_url in seen:
                    continue
                seen.add(document.final_url)
                documents.append(document)
                if len(documents) >= max_articles:
                    break
            if len(rows) < page_size:
                break
            page += 1
    return documents, fetches, failures


def _invalid_payload_message(text: str) -> str:
    snippet = " ".join((text or "").split())[:160]
    if not snippet:
        snippet = "<empty response>"
    if snippet.lower().startswith("<!doctype html") or snippet.lower().startswith("<html"):
        return f"employment API returned HTML instead of JSON: {snippet}"
    return f"employment API returned non-JSON payload: {snippet}"


def _employment_api_url(base_url: str, type_id: str, page: int, page_size: int) -> str:
    query = urlencode({"start_page": 1, "start": page, "count": page_size, "k": "", "type_id": type_id})
    return urljoin(base_url, f"/module/getnotices?{query}")


def _document_from_notice(base_url: str, type_id: str, row: dict) -> ExtractedDocument | None:
    notice_id = str(row.get("notice_id") or "").strip()
    title = str(row.get("notice_name") or "").strip()
    if not notice_id or not title:
        return None
    source_url = str(row.get("content_source_url") or "").strip()
    if source_url:
        final_url = normalize_url(source_url)
    else:
        final_url = normalize_url(urljoin(base_url, f"/detail/news?id={notice_id}&menu_id=23298&type_id={type_id}"))
    body = str(row.get("content") or "").strip()
    if not body and source_url:
        body = f"<p>{title}</p>"
    html = f"<html><head><title>{title}</title></head><body><div class='v_news_content'>{body}</div></body></html>"
    document = extract_document_from_html(final_url, final_url, html)
    published_at = _parse_create_time(str(row.get("create_time") or ""))
    return replace(
        document,
        title=title[:300],
        published_at=published_at or document.published_at,
        date_confidence="exact" if published_at else document.date_confidence,
    )


def _parse_create_time(value: str):
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return None
