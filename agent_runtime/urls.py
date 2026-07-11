from django.urls import path

from . import views

app_name = "agent_runtime"

urlpatterns = [
    path("ask/", views.ask, name="ask"),
    path("ask/stream/", views.ask_stream, name="ask_stream"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path("healthz", views.healthz, name="healthz"),
]
