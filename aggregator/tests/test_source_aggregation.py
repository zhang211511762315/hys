import pytest
from django.utils import timezone

from aggregator.models import ContentItem, ContentSource, Source
from aggregator.services.extraction import ExtractedDocument
from aggregator.services.pipeline import ingest_extracted_document


def make_document(url, title="Same notice"):
    return ExtractedDocument(
        url=url,
        final_url=url,
        title=title,
        html='<div class="v_news_content"><p>Same body about a 2026 notice.</p></div>',
        text="Same body about a 2026 notice.",
        image_urls=[],
        published_at=timezone.datetime(2026, 5, 1, tzinfo=timezone.get_current_timezone()),
    )


@pytest.mark.django_db
def test_same_content_from_multiple_sources_creates_one_item_with_all_sources():
    first = Source.objects.create(name="Official", url="https://www.nuc.edu.cn/", source_type=Source.SourceType.OFFICIAL_SITE)
    second = Source.objects.create(name="College", url="https://cst.nuc.edu.cn/", source_type=Source.SourceType.COLLEGE_SITE)

    first_item = ingest_extracted_document(first, make_document("https://www.nuc.edu.cn/info/1.htm"))
    second_item = ingest_extracted_document(second, make_document("https://cst.nuc.edu.cn/info/2.htm"))

    assert first_item.id == second_item.id
    assert ContentItem.objects.count() == 1
    assert ContentSource.objects.filter(content_item=first_item).count() == 2
    assert set(ContentSource.objects.values_list("source__name", flat=True)) == {"Official", "College"}
