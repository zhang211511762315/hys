from pathlib import Path
import json
from io import StringIO
import os
import subprocess
import sys

import pytest
from django.core.management import call_command, CommandError
from django.test import override_settings

ROOT = Path(__file__).resolve().parents[2]


def test_test_settings_ignore_production_https_environment():
    env = {
        **os.environ,
        "PUBLIC_SITE_BASE_URL": "https://schoolsearchzzychen.online",
        "SECURE_SSL_REDIRECT": "1",
        "SECURE_COOKIES": "1",
        "SECURE_HSTS_SECONDS": "31536000",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; os.environ['DJANGO_SETTINGS_MODULE'] = 'zhongbei_info.settings_test'; "
            "from django.conf import settings; "
            "print(settings.SECURE_SSL_REDIRECT, settings.SESSION_COOKIE_SECURE, settings.SECURE_HSTS_SECONDS)",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False False 0"


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
def test_readiness_and_local_metrics_report_runtime_state():
    from django.test import Client

    client = Client()

    readiness = client.get("/readyz")
    metrics = client.get("/internal/metrics", REMOTE_ADDR="127.0.0.1")
    proxied_metrics = client.get("/internal/metrics", REMOTE_ADDR="172.18.0.2", HTTP_X_INTERNAL_METRICS="1")
    forbidden = client.get("/internal/metrics", REMOTE_ADDR="203.0.113.1")

    assert readiness.status_code == 200
    assert readiness.json()["ok"] is True
    assert metrics.status_code == 200
    assert proxied_metrics.status_code == 200
    assert "hys_published_items" in metrics.content.decode()
    assert forbidden.status_code == 404


def test_nginx_limits_internal_metrics_to_loopback():
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "location = /internal/metrics" in nginx
    assert "allow 127.0.0.1;" in nginx
    assert "deny all;" in nginx
    assert 'proxy_set_header X-Internal-Metrics "1";' in nginx


def test_scheduled_public_site_probe_checks_https_and_certificate():
    workflow = (ROOT / ".github" / "workflows" / "site-monitor.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "schoolsearchzzychen.online" in workflow
    assert "openssl x509 -noout -checkend" in workflow


def test_compose_and_nginx_support_webroot_certificate_renewal():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    service = (ROOT / "deploy" / "systemd" / "hys-certbot-renew.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy" / "systemd" / "hys-certbot-renew.timer").read_text(encoding="utf-8")

    assert "certbot:" in compose
    assert "certbot_webroot" in compose
    assert "location ^~ /.well-known/acme-challenge/" in nginx
    assert "certbot renew --webroot" in service
    assert "nginx -s reload" in service
    assert "OnCalendar=daily" in timer


def test_backup_scripts_use_transactional_dump_and_temporary_restore_container():
    backup = (ROOT / "deploy" / "scripts" / "backup_mysql.sh").read_text(encoding="utf-8")
    restore = (ROOT / "deploy" / "scripts" / "verify_mysql_restore.sh").read_text(encoding="utf-8")

    assert "--single-transaction" in backup
    assert "sha256sum" in backup
    assert "MYSQL_ROOT_PASSWORD" in restore
    assert "trap cleanup EXIT" in restore
    assert "CREATE DATABASE IF NOT EXISTS `zhongbei_info`" in restore
    assert (
        'gunzip -c "${archive}" | docker exec -i "${container}" '
        'mysql -uroot -p"${restore_password}" zhongbei_info'
    ) in restore


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
