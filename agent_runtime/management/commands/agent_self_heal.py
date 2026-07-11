from django.core.management.base import BaseCommand

from agent_runtime.services import run_self_heal


class Command(BaseCommand):
    help = "Run low-cost deterministic self-heal actions. Defaults to dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply safe actions instead of dry-run.")
        parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode. This is the default.")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        result = run_self_heal(dry_run=not options["apply"], limit=options["limit"])
        self.stdout.write(str(result))
