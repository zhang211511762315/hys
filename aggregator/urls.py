from django.urls import path

from . import views, portal

app_name = "aggregator"

urlpatterns = [
    path("projects/", portal.index, name="projects"),
    path("projects/<slug:slug>/", portal.detail, name="project"),
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("categories/<slug:slug>/", views.category_detail, name="category_detail"),
    path("sources/<int:pk>/", views.source_detail, name="source_detail"),
    path("sources/<slug:group>/", views.source_group_view, name="source_group"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
]
