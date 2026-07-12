from datetime import timedelta

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
