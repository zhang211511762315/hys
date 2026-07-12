import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.migrations.recorder import MigrationRecorder

from agent_runtime.models import AgentRun


class Command(BaseCommand):
    help = "Run read-only deployment checks for the Research Agent runtime."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        field_names = {field.name for field in AgentRun._meta.get_fields()}
        replay_field = "replay_of" in field_names
        migration_0005 = MigrationRecorder.Migration.objects.filter(
            app="agent_runtime", name="0005_agentrun_replay_of"
        ).exists()
        route = (getattr(settings, "CELERY_TASK_ROUTES", {}) or {}).get(
            "agent_runtime.tasks.execute_research_run_task", {}
        )
        agent_queue = route.get("queue") if isinstance(route, dict) else None
        checks = {
            "replay_field": replay_field,
            "migration_0005": migration_0005,
            "agent_queue": agent_queue == "agent",
            "daily_limit": int(getattr(settings, "RESEARCH_AGENT_DAILY_LIMIT", 0)) > 0,
            "concurrent_limit": int(getattr(settings, "RESEARCH_AGENT_CONCURRENT_LIMIT", 0)) > 0,
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            if "agent_queue" in failed:
                raise CommandError("Research Agent agent queue is not configured")
            raise CommandError(f"Research Agent smoke failed: {', '.join(failed)}")
        payload = {"ok": True, **checks, "agent_queue": agent_queue}
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(self.style.SUCCESS("Research Agent smoke passed (agent queue ready)"))
