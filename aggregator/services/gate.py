from dataclasses import dataclass
from datetime import date, datetime

from django.conf import settings
from django.utils import timezone

from aggregator.models import ContentItem, Source
from aggregator.services.discovery import is_article_url, is_listing_url
from aggregator.services.extraction import ExtractedDocument

NAVIGATION_TERMS = {
    "首页",
    "学校概况",
    "部门设置",
    "友情链接",
    "联系我们",
    "设为首页",
    "加入收藏",
    "备案",
    "网站首页",
    "下载专区",
    "Home",
    "About",
    "Contact",
}


@dataclass(frozen=True)
class CandidateDecision:
    review_status: str
    is_public: bool
    date_confidence: str
    extraction_quality_score: int
    review_reason: str


def evaluate_candidate(source: Source, document: ExtractedDocument) -> CandidateDecision:
    page_type = classify_page(document.final_url or document.url, document.html, document.text)
    quality = score_extraction_quality(document.title, document.text)
    confidence = _date_confidence(document)
    since = _since_datetime()

    if page_type != "article":
        return CandidateDecision(
            review_status=ContentItem.ReviewStatus.NEEDS_REVIEW,
            is_public=False,
            date_confidence=confidence,
            extraction_quality_score=quality,
            review_reason=f"page type is {page_type}",
        )
    if document.published_at and document.published_at < since:
        return CandidateDecision(
            review_status=ContentItem.ReviewStatus.OUT_OF_RANGE,
            is_public=False,
            date_confidence=confidence,
            extraction_quality_score=quality,
            review_reason="published before 2026-01-01",
        )
    if confidence == ContentItem.DateConfidence.UNKNOWN:
        return CandidateDecision(
            review_status=ContentItem.ReviewStatus.NEEDS_REVIEW,
            is_public=False,
            date_confidence=confidence,
            extraction_quality_score=quality,
            review_reason="published date unknown",
        )
    if confidence != ContentItem.DateConfidence.EXACT:
        return CandidateDecision(
            review_status=ContentItem.ReviewStatus.NEEDS_REVIEW,
            is_public=False,
            date_confidence=confidence,
            extraction_quality_score=quality,
            review_reason=f"published date confidence is {confidence}",
        )
    if quality < 45:
        return CandidateDecision(
            review_status=ContentItem.ReviewStatus.NEEDS_REVIEW,
            is_public=False,
            date_confidence=confidence,
            extraction_quality_score=quality,
            review_reason=f"extraction quality too low ({quality})",
        )
    return CandidateDecision(
        review_status=ContentItem.ReviewStatus.PUBLISHED,
        is_public=True,
        date_confidence=confidence,
        extraction_quality_score=quality,
        review_reason="",
    )


def classify_page(url: str, html: str, text: str) -> str:
    if is_article_url(url):
        return "article"
    if is_listing_url(url, text):
        return "listing"
    return "unknown"


def score_extraction_quality(title: str, text: str) -> int:
    clean_text = (text or "").strip()
    if not clean_text:
        return 0
    score = 0
    length = len(clean_text)
    if length >= 300:
        score += 45
    elif length >= 120:
        score += 30
    elif length >= 50:
        score += 15
    elif length >= 30:
        score += 50
    if title and title[:20] in clean_text:
        score += 10
    nav_hits = sum(1 for term in NAVIGATION_TERMS if term in clean_text)
    score -= min(35, nav_hits * 7)
    unique_lines = {line.strip() for line in clean_text.splitlines() if line.strip()}
    if len(unique_lines) >= 3:
        score += 10
    if "发布时间" in clean_text or "发布日期" in clean_text:
        score += 10
    if "ICP备" in clean_text or "公网安备" in clean_text:
        score -= 20
    return max(0, min(score, 100))


def _date_confidence(document: ExtractedDocument) -> str:
    if document.published_at is None:
        return ContentItem.DateConfidence.UNKNOWN
    confidence = getattr(document, "date_confidence", ContentItem.DateConfidence.EXACT)
    if confidence in ContentItem.DateConfidence.values:
        return confidence
    return ContentItem.DateConfidence.EXACT


def _since_datetime() -> datetime:
    value = getattr(settings, "CRAWL_SINCE_DATE", "2026-01-01")
    parsed = date.fromisoformat(value)
    return timezone.make_aware(datetime(parsed.year, parsed.month, parsed.day), timezone.get_current_timezone())
