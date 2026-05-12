from django.urls import path

from . import views

app_name = "aggregator"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("categories/<slug:slug>/", views.category_detail, name="category_detail"),
    path("sources/<int:pk>/", views.source_detail, name="source_detail"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
]
