import json

from django.core.management.base import BaseCommand, CommandError

from agent_runtime.evaluation.runner import run_evaluation


class Command(BaseCommand):
    help = "Run a versioned, zero-cost-by-default research-agent planner evaluation."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--dataset", default="campus-research-v1")
        parser.add_argument("--strategy", default="single_agent")
        parser.add_argument("--record", action="store_true")

    def handle(self, *args, **options):
        try:
            report = run_evaluation(
                dataset=options["dataset"],
                strategy=options["strategy"],
                record=options["record"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
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
