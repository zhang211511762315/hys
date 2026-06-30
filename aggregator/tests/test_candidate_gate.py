from datetime import datetime

import pytest
from django.utils import timezone

from aggregator.models import ContentItem, Source
from aggregator.services.extraction import ExtractedDocument
from aggregator.services.gate import evaluate_candidate


def make_source(**kwargs):
    defaults = {
        "name": "NUC",
        "url": "https://www.nuc.edu.cn/",
        "source_type": Source.SourceType.OFFICIAL_SITE,
        "priority": Source.Priority.HIGH,
    }
    defaults.update(kwargs)
    return Source(**defaults)


def make_document(**kwargs):
    defaults = {
        "url": "https://www.nuc.edu.cn/info/1013/53873.htm",
        "final_url": "https://www.nuc.edu.cn/info/1013/53873.htm",
        "title": "Important notice",
        "html": '<div class="v_news_content"><p>Important notice body for students.</p></div>',
        "text": "Important notice body for students.",
        "image_urls": [],
        "published_at": timezone.make_aware(datetime(2026, 1, 1)),
    }
    defaults.update(kwargs)
    return ExtractedDocument(**defaults)


def test_candidate_gate_publishes_valid_2026_article():
    decision = evaluate_candidate(make_source(), make_document())

    assert decision.review_status == ContentItem.ReviewStatus.PUBLISHED
    assert decision.is_public is True
    assert decision.date_confidence == ContentItem.DateConfidence.EXACT
    assert decision.extraction_quality_score >= 60


def test_candidate_gate_publishes_2026_article_with_year_only_date():
    document = make_document(
        published_at=timezone.make_aware(datetime(2026, 1, 1)),
        date_confidence=ContentItem.DateConfidence.YEAR_ONLY,
    )

    decision = evaluate_candidate(make_source(), document)

    assert decision.review_status == ContentItem.ReviewStatus.PUBLISHED
    assert decision.is_public is True
    assert decision.date_confidence == ContentItem.DateConfidence.YEAR_ONLY


def test_candidate_gate_blocks_articles_before_2026():
    document = make_document(published_at=timezone.make_aware(datetime(2025, 12, 31)))

    decision = evaluate_candidate(make_source(), document)

    assert decision.review_status == ContentItem.ReviewStatus.OUT_OF_RANGE
    assert decision.is_public is False
    assert "before 2026-01-01" in decision.review_reason


def test_candidate_gate_sends_future_dates_to_review():
    document = make_document(published_at=timezone.now() + timezone.timedelta(days=1))

    decision = evaluate_candidate(make_source(), document)

    assert decision.review_status == ContentItem.ReviewStatus.NEEDS_REVIEW
    assert decision.is_public is False
    assert "future" in decision.review_reason


def test_candidate_gate_sends_unknown_dates_to_review():
    document = make_document(published_at=None)

    decision = evaluate_candidate(make_source(), document)

    assert decision.review_status == ContentItem.ReviewStatus.NEEDS_REVIEW
    assert decision.is_public is False
    assert decision.date_confidence == ContentItem.DateConfidence.UNKNOWN


def test_candidate_gate_sends_low_quality_extraction_to_review():
    document = make_document(text="Home News About Contact", html="<nav>Home News About Contact</nav>")

    decision = evaluate_candidate(make_source(), document)

    assert decision.review_status == ContentItem.ReviewStatus.NEEDS_REVIEW
    assert decision.is_public is False
    assert "quality" in decision.review_reason
