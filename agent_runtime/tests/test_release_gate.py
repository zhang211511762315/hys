import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.recorder import MigrationRecorder
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_release_gate_accepts_complete_schema_without_mutations(monkeypatch):
    monkeypatch.delenv('MYSQL_ROOT_PASSWORD', raising=False)
    call_command('release_check', verbosity=0)


def test_release_gate_refuses_missing_migration(monkeypatch):
    monkeypatch.delenv('MYSQL_ROOT_PASSWORD', raising=False)
    MigrationRecorder.Migration.objects.filter(app='agent_runtime', name='0015_researchrunownership').delete()
    with pytest.raises(CommandError, match='migration gate'): call_command('release_check')


def test_release_gate_refuses_inherited_root_credential(monkeypatch):
    monkeypatch.setenv('MYSQL_ROOT_PASSWORD', 'synthetic-only')
    with pytest.raises(CommandError, match='root credentials'): call_command('release_check')
