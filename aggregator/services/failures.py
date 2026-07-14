from django.db import transaction
from django.utils import timezone

from aggregator.models import CrawlFailure


class CrawlFailureAcknowledgementError(ValueError):
    """Raised when a failure cannot be independently acknowledged as permanent."""


def acknowledge_crawl_failures(
    failure_ids: list[int],
    *,
    note: str,
    confirmed_status: int,
    apply: bool,
) -> list[int]:
    """Validate specific permanent HTTP failures, then optionally record acknowledgement audit data."""
    normalized_ids = list(failure_ids)
    if not normalized_ids:
        raise CrawlFailureAcknowledgementError("at least one failure id is required")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise CrawlFailureAcknowledgementError("failure ids must be unique")
    if not note or not note.strip():
        raise CrawlFailureAcknowledgementError("an acknowledgement note is required")
    if confirmed_status not in {404, 410}:
        raise CrawlFailureAcknowledgementError("confirmed status must be 404 or 410")

    with transaction.atomic():
        failures = list(CrawlFailure.objects.select_for_update().filter(id__in=normalized_ids))
        found_ids = {failure.id for failure in failures}
        if found_ids != set(normalized_ids):
            raise CrawlFailureAcknowledgementError("one or more failure ids do not exist")
        failures_by_id = {failure.id: failure for failure in failures}
        ordered_failures = [failures_by_id[failure_id] for failure_id in normalized_ids]
        for failure in ordered_failures:
            if failure.resolved_at is not None:
                raise CrawlFailureAcknowledgementError("resolved failures cannot be acknowledged")
            if failure.acknowledged_at is not None:
                raise CrawlFailureAcknowledgementError("previously acknowledged failures cannot be acknowledged again")
            if (
                failure.failure_class != CrawlFailure.FailureClass.PERMANENT
                or not failure.permanent
                or failure.http_status not in {404, 410}
                or failure.http_status != confirmed_status
            ):
                raise CrawlFailureAcknowledgementError(
                    "only observed permanent HTTP 404 or 410 failures may be acknowledged"
                )
        if apply:
            now = timezone.now()
            for failure in ordered_failures:
                failure.acknowledged_at = now
                failure.acknowledged_status = confirmed_status
                failure.acknowledged_note = note.strip()
                failure.save(update_fields=["acknowledged_at", "acknowledged_status", "acknowledged_note", "updated_at"])
    return normalized_ids
