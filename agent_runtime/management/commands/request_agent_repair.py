import uuid

from django.core.management.base import BaseCommand

from agent_runtime.research.admin_tools import build_admin_registry
from agent_runtime.research.approvals import request_tool_approval
from agent_runtime.research.runtime import create_research_run


class Command(BaseCommand):
    help = "Create an approval-gated request to retry a failed source."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", type=int, required=True)

    def handle(self, *args, **options):
        source_id = options["source_id"]
        run, _ = create_research_run(
            f"管理员请求诊断并重试来源 {source_id}",
            f"repair-source-{source_id}-{uuid.uuid4().hex[:16]}",
        )
        approval = request_tool_approval(
            run,
            "retry_source",
            {"source_id": source_id},
            build_admin_registry(),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created approval {approval.public_id} for run {run.public_id}; review it in Django admin."
            )
        )
