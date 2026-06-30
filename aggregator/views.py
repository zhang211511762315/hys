from datetime import date, datetime

from django.conf import settings
from django.core.paginator import Paginator
from django.views.decorators.cache import cache_page
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Category, ContentItem, Source
from .services.search import search_items as meili_search

PER_PAGE = 50
DATE_ORDERING = ("-source_published_at", "-published_at", "-created_at")


@cache_page(settings.PAGE_CACHE_SECONDS)
def home(request):
    items, ctx = _apply_sort_and_date_range(request, _published_items())
    page = _page_obj(request, items)
    ctx["page"] = page
    ctx["categories"] = Category.objects.all()
    ctx["source_groups"] = _source_groups_with_counts()
    return render(request, "aggregator/home.html", ctx)


@cache_page(settings.PAGE_CACHE_SECONDS)
def search(request):
    query = request.GET.get("q", "").strip()
    category_slug = request.GET.get("category", "").strip()
    items, ctx = _apply_sort_and_date_range(request, _published_items())
    if query:
        meili_hits = meili_search(query, {"category": category_slug} if category_slug else None)
        if meili_hits:
            ids = [h["id"] for h in meili_hits]
            items = items.filter(id__in=ids)
            if sort != "date":
                id_order = {id: i for i, id in enumerate(ids)}
                items = sorted(items, key=lambda x: id_order.get(x.id, len(ids)))
        else:
            items = items.filter(
                Q(title__icontains=query) | Q(summary__icontains=query) | Q(content_text__icontains=query)
            )
            if category_slug:
                items = items.filter(category__slug=category_slug)
    elif category_slug:
        items = items.filter(category__slug=category_slug)
    page = _page_obj(request, items)
    ctx["page"] = page
    ctx.update(query=query, category_slug=category_slug, categories=Category.objects.all())
    return render(request, "aggregator/search.html", ctx)


@cache_page(settings.PAGE_CACHE_DETAIL_SECONDS)
def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    items, ctx = _apply_sort_and_date_range(request, _published_items().filter(category=category))
    page = _page_obj(request, items)
    ctx["page"] = page
    ctx["category"] = category
    return render(request, "aggregator/category.html", ctx)


@cache_page(settings.PAGE_CACHE_DETAIL_SECONDS)
def source_detail(request, pk):
    source = get_object_or_404(Source, pk=pk)
    items, ctx = _apply_sort_and_date_range(
        request, _published_items().filter(Q(source=source) | Q(content_sources__source=source)).distinct()
    )
    page = _page_obj(request, items)
    ctx["page"] = page
    ctx["source"] = source
    return render(request, "aggregator/source.html", ctx)


@cache_page(settings.PAGE_CACHE_DETAIL_SECONDS)
def source_group_view(request, group):
    valid = {v for v, _ in Source.SourceGroup.choices}
    if group not in valid:
        raise Http404("Unknown source group")
    items, ctx = _apply_sort_and_date_range(
        request, _published_items().filter(source__source_group=group)
    )
    page = _page_obj(request, items)
    ctx["page"] = page
    ctx["source_group"] = group
    ctx["source_group_label"] = dict(Source.SourceGroup.choices)[group]
    ctx["categories"] = Category.objects.all()
    ctx["source_groups"] = _source_groups_with_counts()
    return render(request, "aggregator/source_group.html", ctx)


@cache_page(settings.PAGE_CACHE_DETAIL_SECONDS)
def item_detail(request, pk):
    item = get_object_or_404(_published_items(), pk=pk)
    return render(request, "aggregator/item_detail.html", {"item": item})


def _published_items():
    return (
        ContentItem.objects.filter(
            status=ContentItem.Status.PUBLISHED,
            is_public=True,
            source_published_at__gte=_public_since_datetime(),
            source_published_at__lte=timezone.now(),
        )
        .select_related("source", "category")
        .prefetch_related("tags", "content_sources__source")
        .annotate(
            date_precision_rank=Case(
                When(date_confidence=ContentItem.DateConfidence.EXACT, then=Value(0)),
                When(date_confidence=ContentItem.DateConfidence.YEAR_ONLY, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("-importance_score", "date_precision_rank", "-source_published_at", "-published_at", "-created_at")
    )


def _public_since_datetime():
    value = getattr(settings, "CRAWL_SINCE_DATE", "2026-01-01")
    parsed = date.fromisoformat(value)
    return timezone.make_aware(datetime(parsed.year, parsed.month, parsed.day), timezone.get_current_timezone())


def _page_obj(request, queryset):
    paginator = Paginator(queryset, PER_PAGE)
    page_number = request.GET.get("page", 1)
    return paginator.get_page(page_number)


def _apply_sort_and_date_range(request, queryset):
    sort = request.GET.get("sort", "relevance")
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    if date_from:
        queryset = queryset.filter(source_published_at__gte=_parse_date_start(date_from))
    if date_to:
        queryset = queryset.filter(source_published_at__lte=_parse_date_end(date_to))

    if sort == "date":
        queryset = queryset.order_by(*DATE_ORDERING)

    ctx = {
        "sort": sort,
        "date_from": date_from,
        "date_to": date_to,
        "base_query": _base_query(request),
    }
    return queryset, ctx


def _source_groups_with_counts():
    published = ContentItem.objects.filter(
        status=ContentItem.Status.PUBLISHED, is_public=True,
        source_published_at__gte=_public_since_datetime(),
        source_published_at__lte=timezone.now(),
    )
    groups = []
    for value, label in Source.SourceGroup.choices:
        count = published.filter(source__source_group=value).count()
        if count:
            groups.append((value, label, count))
    return groups


def _parse_date_start(raw):
    try:
        d = date.fromisoformat(raw)
        return timezone.make_aware(datetime(d.year, d.month, d.day), timezone.get_current_timezone())
    except (ValueError, TypeError):
        return None


def _parse_date_end(raw):
    try:
        d = date.fromisoformat(raw)
        return timezone.make_aware(datetime(d.year, d.month, d.day, 23, 59, 59), timezone.get_current_timezone())
    except (ValueError, TypeError):
        return None


def _base_query(request):
    params = request.GET.copy()
    for key in ("page",):
        params.pop(key, None)
    return params.urlencode()
