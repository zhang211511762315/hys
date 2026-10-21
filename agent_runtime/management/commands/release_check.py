"""Read-only release gate. Never migrates or initializes production state."""
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from agent_runtime.models import AgentRun, ResearchRunOwnership


class Command(BaseCommand):
    help = 'Require the complete release schema, owner FK and isolated research queue.'

    def handle(self, *args, **options):
        if os.getenv('MYSQL_ROOT_PASSWORD'):
            raise CommandError('application must not receive database root credentials')
        route = settings.CELERY_TASK_ROUTES.get('agent_runtime.tasks.execute_research_run_task', {})
        if route.get('queue') != 'agent_v2':
            raise CommandError('versioned research queue is not configured')
        if not MigrationRecorder.Migration.objects.filter(app='agent_runtime', name='0015_researchrunownership').exists():
            raise CommandError('release migration gate not complete; keep the current application')
        with connection.cursor() as cursor:
            columns = {c.name: c for c in connection.introspection.get_table_description(cursor, AgentRun._meta.db_table)}
            constraints = connection.introspection.get_constraints(cursor, ResearchRunOwnership._meta.db_table)
        if not ('dispatch_meta' in columns and columns['dispatch_meta'].null_ok):
            raise CommandError('backward-compatible nullable columns required')
        owner = ResearchRunOwnership._meta.get_field('owner')
        target = (owner.target_field.model._meta.db_table, owner.target_field.column)
        if not any(c.get('foreign_key') == target and c.get('columns') == ['owner_id'] for c in constraints.values()):
            raise CommandError('owner foreign key missing; do not release')
        if not any(c.get('index') and c.get('columns') == ['owner_id'] for c in constraints.values()):
            raise CommandError('owner index missing; do not release')
        run_target = (AgentRun._meta.db_table, AgentRun._meta.pk.column)
        if not any(c.get('foreign_key') == run_target and c.get('columns') == ['run_id'] for c in constraints.values()):
            raise CommandError('run foreign key missing; do not release')
        if not any((c.get('primary_key') or c.get('unique')) and c.get('columns') == ['run_id'] for c in constraints.values()):
            raise CommandError('run ownership must be unique')
        if getattr(settings, 'PUBLIC_WORKSPACE_ENABLED', False):
            from agent_runtime.public_workspace import identity
            try:
                user = identity()
            except Exception as exc:
                raise CommandError('public workspace is not provisioned') from exc
            if user.has_usable_password() or user.has_perm('auth.change_user') or not user.has_perm('aggregator.change_source'):
                raise CommandError('public workspace permissions invalid')
        self.stdout.write('release schema and queue ready')
