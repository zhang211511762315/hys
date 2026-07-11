from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Callable

from django.db.models import Q
from pydantic import BaseModel

from aggregator.models import ContentItem

from .schemas import (
    BuildTimelineInput,
    BuildTimelineOutput,
    CompareEvidenceInput,
    CompareEvidenceOutput,
    ContentEvidence,
    GetContentDetailsInput,
    GetContentDetailsOutput,
    SearchContentInput,
    SearchContentOutput,
)


class RiskLevel(StrEnum):
    LOW = "low"
    HIGH = "high"


class ToolPermission(StrEnum):
    PUBLIC = "public"
    STAFF = "staff"


@dataclass(frozen=True)
class ToolContext:
    actor_is_staff: bool = False
    run_id: str = ""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: RiskLevel
    permission: ToolPermission
    timeout_seconds: int
    max_retries: int
    idempotent: bool
    executor: Callable[[BaseModel, ToolContext], BaseModel | dict[str, Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def execute(self, name: str, payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        spec = self.get(name)
        if spec.permission == ToolPermission.STAFF and not context.actor_is_staff:
            raise PermissionError(f"tool {name} requires staff permission")
        validated_input = spec.input_model.model_validate(payload)
        raw_output = spec.executor(validated_input, context)
        return spec.output_model.model_validate(raw_output).model_dump(mode="json")


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search_public_content",
            version="1",
            input_model=SearchContentInput,
            output_model=SearchContentOutput,
            risk_level=RiskLevel.LOW,
            permission=ToolPermission.PUBLIC,
            timeout_seconds=5,
            max_retries=1,
            idempotent=True,
            executor=_search_public_content,
        )
    )
    registry.register(
        ToolSpec(
            name="get_content_details",
            version="1",
            input_model=GetContentDetailsInput,
            output_model=GetContentDetailsOutput,
            risk_level=RiskLevel.LOW,
            permission=ToolPermission.PUBLIC,
            timeout_seconds=5,
            max_retries=1,
            idempotent=True,
            executor=_get_content_details,
        )
    )
    registry.register(
        ToolSpec(
            name="build_deadline_timeline",
            version="1",
            input_model=BuildTimelineInput,
            output_model=BuildTimelineOutput,
            risk_level=RiskLevel.LOW,
            permission=ToolPermission.PUBLIC,
            timeout_seconds=5,
            max_retries=0,
            idempotent=True,
            executor=_build_deadline_timeline,
        )
    )
    registry.register(
        ToolSpec(
            name="compare_evidence",
            version="1",
            input_model=CompareEvidenceInput,
            output_model=CompareEvidenceOutput,
            risk_level=RiskLevel.LOW,
            permission=ToolPermission.PUBLIC,
            timeout_seconds=5,
            max_retries=0,
            idempotent=True,
            executor=_compare_evidence,
        )
    )
    return registry


def _query_terms(query: str) -> list[str]:
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", query))
    terms = re.findall(r"[A-Za-z0-9]+", query)
    for size in (2, 3, 4):
        terms.extend(cjk[index : index + size] for index in range(max(0, len(cjk) - size + 1)))
    stop = {"整理", "最近", "信息", "校园", "报名", "时间", "哪些", "相关"}
    return list(dict.fromkeys(term for term in terms if term and term not in stop))[:20]


def _to_evidence(item: ContentItem) -> ContentEvidence:
    text = (item.summary or item.content_text or "").strip()
    return ContentEvidence(
        item_id=item.id,
        title=item.title,
        source=item.source.name,
        url=item.canonical_url,
        snippet=text[:500],
        published_at=item.source_published_at.isoformat() if item.source_published_at else "",
    )


def _search_public_content(payload: SearchContentInput, _context: ToolContext) -> dict[str, Any]:
    queryset = ContentItem.objects.filter(status=ContentItem.Status.PUBLISHED, is_public=True).select_related("source")
    terms = _query_terms(payload.query)
    if terms:
        predicate = Q()
        for term in terms:
            predicate |= Q(title__icontains=term) | Q(summary__icontains=term) | Q(content_text__icontains=term)
        queryset = queryset.filter(predicate)
    else:
        queryset = queryset.none()
    candidates = list(queryset[:100])
    candidates.sort(
        key=lambda item: (
            sum(f"{item.title} {item.summary} {item.content_text}".count(term) for term in terms),
            item.importance_score,
            item.id,
        ),
        reverse=True,
    )
    items = [_to_evidence(item) for item in candidates[: payload.limit]]
    return SearchContentOutput(item_ids=[item.item_id for item in items], items=items).model_dump()


def _get_content_details(payload: GetContentDetailsInput, _context: ToolContext) -> dict[str, Any]:
    rows = ContentItem.objects.filter(
        id__in=payload.item_ids,
        status=ContentItem.Status.PUBLISHED,
        is_public=True,
    ).select_related("source")
    by_id = {item.id: item for item in rows}
    items = [_to_evidence(by_id[item_id]) for item_id in payload.item_ids if item_id in by_id]
    return GetContentDetailsOutput(items=items).model_dump()


DATE_PATTERNS = (
    re.compile(r"20\d{2}年\d{1,2}月\d{1,2}日"),
    re.compile(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"),
)


def _build_deadline_timeline(payload: BuildTimelineInput, _context: ToolContext) -> dict[str, Any]:
    entries = []
    for item in payload.items:
        haystack = f"{item.title} {item.snippet}"
        date_text = next((match.group(0) for pattern in DATE_PATTERNS if (match := pattern.search(haystack))), "")
        if date_text:
            entries.append({"item_id": item.item_id, "title": item.title, "date_text": date_text})
    return BuildTimelineOutput(entries=entries).model_dump()


def _compare_evidence(payload: CompareEvidenceInput, _context: ToolContext) -> dict[str, Any]:
    groups: dict[str, list[int]] = {}
    for item in payload.items:
        groups.setdefault(item.source, []).append(item.item_id)
    return CompareEvidenceOutput(groups=groups).model_dump()
