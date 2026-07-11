from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("favicon.ico", views.favicon, name="favicon"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("admin/", admin.site.urls),
    path("", include("agent_runtime.urls")),
    path("", include("aggregator.urls")),
]
