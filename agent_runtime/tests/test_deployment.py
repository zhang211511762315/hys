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


def test_production_nginx_has_domain_https_and_http_redirect():
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "server_name schoolsearchzzychen.online www.schoolsearchzzychen.online;" in nginx
    assert "listen 443 ssl;" in nginx
    assert "ssl_certificate /etc/letsencrypt/live/schoolsearchzzychen.online/fullchain.pem;" in nginx
    assert "ssl_certificate_key /etc/letsencrypt/live/schoolsearchzzychen.online/privkey.pem;" in nginx
    assert "return 301 https://$host$request_uri;" in nginx


def test_compose_publishes_https_and_mounts_certificates():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"443:443"' in compose
    assert "/etc/letsencrypt:/etc/letsencrypt:ro" in compose


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


def test_existing_agentruns_get_unique_public_ids_during_migration():
    import importlib

    migration = importlib.import_module("agent_runtime.migrations.0003_research_runtime")

    operations = migration.Migration.operations
    assert any(operation.__class__.__name__ == "RunPython" for operation in operations)
    add_public_id = next(
        operation for operation in operations
        if operation.__class__.__name__ == "AddField" and operation.name == "public_id"
    )
    assert add_public_id.field.null is True
    assert add_public_id.field.unique is False
