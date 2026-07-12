from django.urls import path

from . import views

app_name = "agent_runtime"

urlpatterns = [
    path("api/v1/research-runs", views.research_runs, name="research_runs"),
    path("api/v1/research-runs/<uuid:run_id>", views.research_run_detail, name="research_run_detail"),
    path("api/v1/research-runs/<uuid:run_id>/events", views.research_run_events, name="research_run_events"),
    path("api/v1/research-runs/<uuid:run_id>/cancel", views.cancel_research_run_view, name="cancel_research_run"),
    path("api/v1/research-runs/<uuid:run_id>/replay", views.replay_research_run_view, name="replay_research_run"),
    path("research/", views.research, name="research"),
    path("ask/", views.ask, name="ask"),
    path("ask/stream/", views.ask_stream, name="ask_stream"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path("healthz", views.healthz, name="healthz"),
]
