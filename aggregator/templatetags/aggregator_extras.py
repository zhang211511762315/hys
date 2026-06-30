from django import template
from django.utils import timezone

from aggregator.models import ContentItem


register = template.Library()


@register.filter
def display_item_date(item: ContentItem) -> str:
    if item.source_published_at:
        local_value = timezone.localtime(item.source_published_at)
        if item.date_confidence == ContentItem.DateConfidence.YEAR_ONLY:
            return f"{local_value.year} 年（日期待确认）"
        return local_value.strftime("%Y-%m-%d %H:%M")
    if item.published_at:
        return timezone.localtime(item.published_at).strftime("%Y-%m-%d %H:%M")
    return ""
