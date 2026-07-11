import json

from django.core.management.base import BaseCommand

from agent_runtime.evaluation.runner import run_planner_evaluation


class Command(BaseCommand):
    help = "Run the versioned zero-cost research-agent planner evaluation."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        report = run_planner_evaluation()
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"cases={report['case_count']} plan_valid={report['plan_valid_rate']:.2%} "
                f"tool_accuracy={report['tool_selection_accuracy']:.2%} "
                f"unsafe={report['unsafe_tool_selection_count']}"
            )
        )
