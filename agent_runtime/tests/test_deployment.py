from pathlib import Path


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
