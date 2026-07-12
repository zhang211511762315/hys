from pathlib import Path
import json
from io import StringIO

import pytest
from django.core.management import call_command, CommandError
from django.test import override_settings

ROOT = Path(__file__).resolve().parents[2]


def test_compose_has_durable_redis_and_dedicated_agent_worker():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "--appendonly" in compose
    assert "redis_data:/data" in compose
    assert "agent_worker:" in compose
    assert '"--queues=agent"' in compose
    assert "condition: service_healthy" in compose


def test_production_nginx_has_no_undeclared_test_upstream():
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "hys-test-web" not in nginx
    assert "location /__test/" not in nginx


@pytest.mark.django_db
def test_research_agent_smoke_reports_ready_runtime():
    output = StringIO()

    call_command("research_agent_smoke", "--json", stdout=output)

    payload = json.loads(output.getvalue())
    assert payload["ok"] is True
    assert payload["agent_queue"] == "agent"
    assert payload["replay_field"] is True
    assert payload["migration_0005"] is True
    assert "DEEPSEEK_API_KEY" not in output.getvalue()


@pytest.mark.django_db
@override_settings(CELERY_TASK_ROUTES={})
def test_research_agent_smoke_fails_when_agent_queue_is_missing():
    with pytest.raises(CommandError, match="agent queue"):
        call_command("research_agent_smoke")
