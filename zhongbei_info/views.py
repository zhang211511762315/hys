import math
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from aggregator.models import ContentItem, Source


def robots_txt(request):
    base_url = _base_url(request).rstrip("/")
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            f"Sitemap: {base_url}/sitemap-index.xml",
            "",
        ]
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def favicon(request):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#1769aa"/><path d="M14 18h36v8H29v6h18v8H29v18h-9V26h-6z" fill="#fff"/></svg>"""
    return HttpResponse(svg, content_type="image/svg+xml")


def sitemap_xml(request):
    return sitemap_items_xml(request, page=1)


SITEMAP_PAGE_SIZE = 500


def sitemap_index_xml(request):
    base_url = _base_url(request).rstrip("/")
    static_count = 2 + len(Source.SourceGroup.choices)
    item_count = ContentItem.objects.filter(
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at__lte=timezone.now(),
    ).count()
    first_page_capacity = max(1, SITEMAP_PAGE_SIZE - static_count)
    page_count = max(1, 1 + math.ceil(max(0, item_count - first_page_capacity) / SITEMAP_PAGE_SIZE))
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page in range(1, page_count + 1):
        location = "/sitemap.xml" if page == 1 else f"/sitemap-items-{page}.xml"
        body.extend(["  <sitemap>", f"    <loc>{escape(base_url + location)}</loc>", "  </sitemap>"])
    body.append("</sitemapindex>")
    return HttpResponse("\n".join(body), content_type="application/xml; charset=utf-8")


def sitemap_items_xml(request, page: int = 1):
    page = max(1, int(page))
    base_url = _base_url(request).rstrip("/")
    static_urls = [
        (base_url + reverse("aggregator:home"), timezone.now()),
        (base_url + reverse("aggregator:search"), timezone.now()),
    ]
    static_urls.extend(
        (base_url + reverse("aggregator:source_group", args=[value]), timezone.now())
        for value, _label in Source.SourceGroup.choices
    )

    item_queryset = ContentItem.objects.filter(
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
        source_published_at__lte=timezone.now(),
    ).order_by("-source_published_at").only("id", "updated_at")
    if page == 1:
        item_slice = item_queryset[: max(0, SITEMAP_PAGE_SIZE - len(static_urls))]
        urls = static_urls + [
            (base_url + reverse("aggregator:item_detail", args=[item.id]), item.updated_at)
            for item in item_slice
        ]
    else:
        offset = max(0, SITEMAP_PAGE_SIZE - len(static_urls)) + (page - 2) * SITEMAP_PAGE_SIZE
        item_slice = item_queryset[offset : offset + SITEMAP_PAGE_SIZE]
        urls = [
            (base_url + reverse("aggregator:item_detail", args=[item.id]), item.updated_at)
            for item in item_slice
        ]

    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in urls:
        body.extend(
            [
                "  <url>",
                f"    <loc>{escape(loc)}</loc>",
                f"    <lastmod>{lastmod.date().isoformat()}</lastmod>",
                "  </url>",
            ]
        )
    body.append("</urlset>")
    return HttpResponse("\n".join(body), content_type="application/xml; charset=utf-8")


def _base_url(request):
    configured = getattr(settings, "PUBLIC_SITE_BASE_URL", "")
    if configured:
        return configured
    return request.build_absolute_uri("/")
