from datetime import timedelta
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone


@pytest.mark.django_db
def test_signup_creates_authenticated_account():
    client = Client()

    response = client.post(
        "/accounts/signup/",
        {
            "username": "student-user",
            "password1": "safe-test-password-123",
            "password2": "safe-test-password-123",
        },
    )

    assert response.status_code == 302
    assert response.url == "/account/privacy/"
    assert get_user_model().objects.filter(username="student-user").exists()
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_memory_api_requires_authenticated_user():
    response = Client().get("/api/v1/memory")

    assert response.status_code == 403


@pytest.mark.django_db
def test_user_can_read_and_delete_only_own_memory():
    from agent_runtime.models import MemoryEntry

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="owner", password="safe-test-password-123")
    other = user_model.objects.create_user(username="other", password="safe-test-password-123")
    expires_at = timezone.now() + timedelta(days=1)
    owned = MemoryEntry.objects.create(user=owner, content="我关注就业信息", consented_at=timezone.now(), expires_at=expires_at)
    MemoryEntry.objects.create(user=other, content="不应泄露", consented_at=timezone.now(), expires_at=expires_at)
    client = Client()
    client.login(username="owner", password="safe-test-password-123")

    listing = client.get("/api/v1/memory")
    deletion = client.delete(f"/api/v1/memory/{owned.public_id}")

    assert listing.status_code == 200
    assert listing.json()["memories"] == [{"id": str(owned.public_id), "content": "我关注就业信息"}]
    assert deletion.status_code == 204
    assert not MemoryEntry.objects.filter(id=owned.id).exists()
    assert MemoryEntry.objects.filter(user=other).exists()


@pytest.mark.django_db
def test_expired_memory_cleanup_keeps_unexpired_entries():
    from agent_runtime.models import MemoryEntry
    from agent_runtime.services import cleanup_expired_memory

    user = get_user_model().objects.create_user(username="cleanup", password="safe-test-password-123")
    expired = MemoryEntry.objects.create(
        user=user,
        content="过期偏好",
        consented_at=timezone.now() - timedelta(days=181),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    active = MemoryEntry.objects.create(
        user=user,
        content="有效偏好",
        consented_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=1),
    )

    result = cleanup_expired_memory()

    assert result["memory_deleted"] == 1
    assert not MemoryEntry.objects.filter(id=expired.id).exists()
    assert MemoryEntry.objects.filter(id=active.id).exists()


@pytest.mark.django_db
def test_account_memory_form_saves_explicit_memory_for_current_user():
    from agent_runtime.models import MemoryEntry

    user = get_user_model().objects.create_user(username="memory-owner", password="safe-test-password-123")
    client = Client()
    client.login(username="memory-owner", password="safe-test-password-123")

    response = client.post("/account/memory/save/", {"content": "我关注研究生招生"})

    assert response.status_code == 302
    memory = MemoryEntry.objects.get(user=user)
    assert memory.content == "我关注研究生招生"
    assert memory.consented_at is not None


@pytest.mark.django_db
def test_memory_export_contains_only_current_users_data_and_is_json_attachment():
    from agent_runtime.models import MemoryEntry

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="export-owner", password="safe-test-password-123")
    other = user_model.objects.create_user(username="export-other", password="safe-test-password-123")
    expires_at = timezone.now() + timedelta(days=1)
    MemoryEntry.objects.create(user=owner, content="我的导出内容", consented_at=timezone.now(), expires_at=expires_at)
    MemoryEntry.objects.create(user=other, content="绝不能导出", consented_at=timezone.now(), expires_at=expires_at)
    client = Client()
    client.login(username="export-owner", password="safe-test-password-123")

    response = client.get("/account/memory-export/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response["Content-Disposition"] == 'attachment; filename="memory-export.json"'
    payload = json.loads(response.content)
    assert [item["content"] for item in payload["memories"]] == ["我的导出内容"]


@pytest.mark.django_db
def test_account_memory_delete_post_is_scoped_to_current_user():
    from agent_runtime.models import MemoryEntry

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="delete-owner", password="safe-test-password-123")
    other = user_model.objects.create_user(username="delete-other", password="safe-test-password-123")
    expires_at = timezone.now() + timedelta(days=1)
    owned = MemoryEntry.objects.create(user=owner, content="删除我", consented_at=timezone.now(), expires_at=expires_at)
    foreign = MemoryEntry.objects.create(user=other, content="保留我", consented_at=timezone.now(), expires_at=expires_at)
    client = Client()
    client.login(username="delete-owner", password="safe-test-password-123")

    foreign_response = client.post(f"/account/memory/{foreign.public_id}/delete/")
    owned_response = client.post(f"/account/memory/{owned.public_id}/delete/")

    assert foreign_response.status_code == 404
    assert owned_response.status_code == 302
    assert not MemoryEntry.objects.filter(id=owned.id).exists()
    assert MemoryEntry.objects.filter(id=foreign.id).exists()


@pytest.mark.django_db
def test_authenticated_session_key_cannot_attach_or_read_another_users_session():
    from agent_runtime.models import RagSession
    from agent_runtime.services import get_or_create_session

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="session-owner", password="safe-test-password-123")
    other = user_model.objects.create_user(username="session-other", password="safe-test-password-123")
    foreign_session = RagSession.objects.create(session_key="other-users-session", user=other)

    session = get_or_create_session(foreign_session.session_key, user=owner)

    assert session.user_id == owner.id
    assert session.session_key != foreign_session.session_key
    foreign_session.refresh_from_db()
    assert foreign_session.user_id == other.id


@pytest.mark.django_db
def test_authenticated_ask_page_rejects_foreign_session_key():
    from agent_runtime.models import RagSession

    user_model = get_user_model()
    owner = user_model.objects.create_user(username="ask-owner", password="safe-test-password-123")
    other = user_model.objects.create_user(username="ask-other", password="safe-test-password-123")
    foreign_session = RagSession.objects.create(session_key="foreign-ask-session", user=other)
    client = Client()
    client.login(username="ask-owner", password="safe-test-password-123")

    response = client.get(f"/ask/?session={foreign_session.session_key}")

    assert response.status_code == 200
    assert response.cookies["rag_session_key"].value != foreign_session.session_key


@pytest.mark.django_db
def test_long_term_memory_is_not_injected_into_rag_prompts(monkeypatch):
    from agent_runtime.models import MemoryEntry
    from agent_runtime.services import answer_question_events

    user = get_user_model().objects.create_user(username="no-auto-memory", password="safe-test-password-123")
    MemoryEntry.objects.create(
        user=user,
        content="long-term secret preference",
        consented_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=1),
    )
    prompts = []
    monkeypatch.setattr("agent_runtime.services.retrieve_contexts", lambda _question: [])
    monkeypatch.setattr("agent_runtime.services.build_rag_graph", lambda: None)
    monkeypatch.setattr(
        "agent_runtime.services._generate_answer",
        lambda prompt, _contexts, _estimate: (prompts.append(prompt) or "回答", {}, "budget_or_key_unavailable"),
    )

    list(answer_question_events("公开问题", user=user))

    assert prompts
    assert "long-term secret preference" not in prompts[0]
