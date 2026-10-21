import json
from unittest.mock import Mock
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, AsyncClient
from django.utils import timezone
from agent_runtime.models import MemoryEntry, RagSession, AgentRun
from agent_runtime.public_workspace import USERNAME

pytestmark = pytest.mark.django_db

@pytest.fixture
def public(settings,tmp_path):
    call_command('prepare_public_workspace',verbosity=0)
    settings.PUBLIC_WORKSPACE_ENABLED=True
    path=tmp_path/'state.json';path.write_text(json.dumps({'hys':True,'rp-chat':True,'mobile-rp':True,'rss':True}))
    settings.PORTAL_STATE_FILE=str(path)
    return get_user_model().objects.get(username=USERNAME)


def test_projects_have_three_top_level_entries_and_nested_rss(client,public):
    from aggregator.portal import projects
    data=projects()
    assert [p['slug'] for p in data]==['hys','rp-chat','mobile-rp']
    assert all('/hys/rss/' not in f['href'] for p in data[1:] for g in p['groups'] for f in g['features'])
    assert any('/hys/rss/' in f['href'] for g in data[0]['groups'] for f in g['features'])
    for url in ['/projects/','/projects/hys/','/projects/rp-chat/','/projects/mobile-rp/','/research/','/account/privacy/']:
        response=client.get(url)
        assert response.status_code==200,url
        assert 'name="password"' not in response.content.decode()
    assert client.get('/projects/wewe-rss/').status_code==404


def test_public_identity_has_no_system_user_permissions(client,public):
    assert public.is_staff and not public.is_superuser and not public.has_usable_password()
    assert public.has_perm('aggregator.change_source')
    assert not public.has_perm('auth.change_user')
    assert client.get('/admin/aggregator/source/').status_code==200
    assert client.get('/admin/auth/user/').status_code==404
    assert client.post('/account/delete/').status_code==404
    assert get_user_model().objects.filter(pk=public.pk).exists()


def test_public_memory_reads_legacy_ownership_without_reassigning(client,public):
    old=get_user_model().objects.create_user('fixture-old')
    memory=MemoryEntry.objects.create(user=old,content='synthetic prior memory',consented_at=timezone.now(),expires_at=timezone.now()+timezone.timedelta(days=1))
    session=RagSession.objects.create(user=old,session_key='fixture-legacy-session',expires_at=timezone.now()+timezone.timedelta(days=1))
    assert 'synthetic prior memory' in client.get('/account/privacy/').content.decode()
    assert client.get('/api/v1/memory').json()['memories'][0]['id']==str(memory.public_id)
    from agent_runtime.services import get_or_create_session
    assert get_or_create_session(session.session_key,user=public).pk==session.pk
    session.refresh_from_db();assert session.user_id==old.pk
    memory.refresh_from_db();assert memory.user_id==old.pk


def test_new_memory_owned_by_fixed_workspace_and_csrf_required(public):
    client=Client(enforce_csrf_checks=True)
    assert client.post('/api/v1/memory',json.dumps({'content':'fixture'}),content_type='application/json').status_code==403
    client.get('/account/privacy/')
    token=client.cookies['csrftoken'].value
    response=client.post('/api/v1/memory',json.dumps({'content':'fixture new memory'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
    assert response.status_code==201
    assert MemoryEntry.objects.get(public_id=response.json()['id']).user_id==public.pk


def test_public_research_quota_counts_previous_owners(client,public,settings,monkeypatch):
    from agent_runtime import admission
    monkeypatch.setattr(admission.execute_research_run_task,'delay',Mock())
    old=get_user_model().objects.create_user('fixture-previous')
    from agent_runtime.research.runtime import create_research_run
    run,_=create_research_run('fixture','fixture-old-id',owner=old)
    run.status=AgentRun.Status.SUCCEEDED;run.save()
    settings.RESEARCH_AGENT_DAILY_LIMIT=1
    response=client.post('/api/v1/research-runs',json.dumps({'goal':'fixture new','client_request_id':'fixture-new-id'}),content_type='application/json')
    assert response.status_code==429
    admission.execute_research_run_task.delay.assert_not_called()


def test_public_flag_off_restores_research_login_and_owner_isolation(client,public,settings):
    settings.PUBLIC_WORKSPACE_ENABLED=False
    assert client.get('/research/').status_code==302
    assert client.post('/api/v1/research-runs').status_code==401
    assert client.get('/api/v1/memory').status_code==403


@pytest.mark.django_db(transaction=True)
def test_async_requests_share_the_same_workspace(public):
    from asgiref.sync import async_to_sync
    response=async_to_sync(AsyncClient().get)('/research/')
    assert response.status_code==200
    assert '公开共享工作区' in response.content.decode()
