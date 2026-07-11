import json

from django.core.management.base import BaseCommand

from agent_runtime.services import run_agent_eval


class Command(BaseCommand):
    help = "Run a lightweight retrieval evaluation over fixed campus-information questions."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output structured JSON.")

    def handle(self, *args, **options):
        result = run_agent_eval(record=True)
        if options["json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return

        for case in result["cases"]:
            self.stdout.write(
                (
                    f"{case['question']}: {case['context_count']} context(s), "
                    f"hit={case['hit']}, expected_keyword_hit={case['expected_keyword_hit']}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                (
                    f"retrieval_hit_rate={result['retrieval_hit_rate']:.2%}; "
                    f"expected_keyword_hit_rate={result['expected_keyword_hit_rate']:.2%}; "
                    f"citation_coverage_rate={result['citation_coverage_rate']:.2%}; "
                    f"paid_llm_calls={result['paid_llm_calls']}; total_cost_cny={result['total_cost_cny']}"
                )
            )
        )
