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
            f"Sitemap: {base_url}/sitemap.xml",
            "",
        ]
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def favicon(request):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#1769aa"/><path d="M14 18h36v8H29v6h18v8H29v18h-9V26h-6z" fill="#fff"/></svg>"""
    return HttpResponse(svg, content_type="image/svg+xml")


def sitemap_xml(request):
    base_url = _base_url(request).rstrip("/")
    urls = [
        (base_url + reverse("aggregator:home"), timezone.now()),
        (base_url + reverse("aggregator:search"), timezone.now()),
    ]

    for value, _label in Source.SourceGroup.choices:
        urls.append((base_url + reverse("aggregator:source_group", args=[value]), timezone.now()))

    items = (
        ContentItem.objects.filter(
            status=ContentItem.Status.PUBLISHED,
            is_public=True,
            source_published_at__lte=timezone.now(),
        )
        .order_by("-source_published_at")
        .only("id", "updated_at")[:500]
    )
    urls.extend((base_url + reverse("aggregator:item_detail", args=[item.id]), item.updated_at) for item in items)

    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in urls:
        body.extend(
            [
                "  <url>",
                f"    <loc>{loc}</loc>",
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
