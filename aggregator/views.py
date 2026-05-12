from datetime import date, datetime

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Category, ContentItem, Source


def home(request):
    items = _published_items()[:30]
    return render(request, "aggregator/home.html", {"items": items, "categories": Category.objects.all()})


def search(request):
    query = request.GET.get("q", "").strip()
    category_slug = request.GET.get("category", "").strip()
    items = _published_items()
    if query:
        items = items.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(content_text__icontains=query))
    if category_slug:
        items = items.filter(category__slug=category_slug)
    return render(
        request,
        "aggregator/search.html",
        {"items": items[:50], "query": query, "category_slug": category_slug, "categories": Category.objects.all()},
    )


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    items = _published_items().filter(category=category)[:50]
    return render(request, "aggregator/category.html", {"category": category, "items": items})


def source_detail(request, pk):
    source = get_object_or_404(Source, pk=pk)
    items = _published_items().filter(Q(source=source) | Q(content_sources__source=source)).distinct()[:50]
    return render(request, "aggregator/source.html", {"source": source, "items": items})


def item_detail(request, pk):
    item = get_object_or_404(_published_items(), pk=pk)
    return render(request, "aggregator/item_detail.html", {"item": item})


def _published_items():
    return (
        ContentItem.objects.filter(
            status=ContentItem.Status.PUBLISHED,
            is_public=True,
            source_published_at__gte=_public_since_datetime(),
        )
        .select_related("source", "category")
        .prefetch_related("tags", "content_sources__source")
        .order_by("-importance_score", "-source_published_at", "-published_at", "-created_at")
    )


def _public_since_datetime():
    value = getattr(settings, "CRAWL_SINCE_DATE", "2026-01-01")
    parsed = date.fromisoformat(value)
    return timezone.make_aware(datetime(parsed.year, parsed.month, parsed.day), timezone.get_current_timezone())
