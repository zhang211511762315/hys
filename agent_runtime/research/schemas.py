from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    args: dict[str, Any] = Field(default_factory=dict)
    input_from: dict[str, str] = Field(default_factory=dict)


class ResearchPlan(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    task_type: Literal["search", "deadline_research", "comparison"]
    steps: list[PlanStep] = Field(min_length=1, max_length=6)


class ContentEvidence(BaseModel):
    item_id: int
    title: str
    source: str
    url: str
    snippet: str
    published_at: str = ""


class SearchContentInput(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=20)
    source_names: list[str] = Field(default_factory=list, max_length=10)
    category_slugs: list[str] = Field(default_factory=list, max_length=10)
    published_after: date | None = None
    published_before: date | None = None


class SearchContentOutput(BaseModel):
    item_ids: list[int] = Field(default_factory=list)
    items: list[ContentEvidence] = Field(default_factory=list)


class GetContentDetailsInput(BaseModel):
    item_ids: list[int] = Field(default_factory=list, max_length=20)


class GetContentDetailsOutput(BaseModel):
    items: list[ContentEvidence] = Field(default_factory=list)


class BuildTimelineInput(BaseModel):
    items: list[ContentEvidence] = Field(default_factory=list, max_length=20)


class TimelineEntry(BaseModel):
    item_id: int
    title: str
    date_text: str


class BuildTimelineOutput(BaseModel):
    entries: list[TimelineEntry] = Field(default_factory=list)


class CompareEvidenceInput(BaseModel):
    items: list[ContentEvidence] = Field(default_factory=list, max_length=20)


class CompareEvidenceOutput(BaseModel):
    groups: dict[str, list[int]] = Field(default_factory=dict)


class AnswerCitation(BaseModel):
    item_id: int
    title: str
    source: str
    url: str


class ResearchAnswer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[AnswerCitation] = Field(default_factory=list)
    insufficient_evidence: bool = False


class VerificationResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class CreateResearchRunInput(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    client_request_id: str = Field(min_length=8, max_length=120)
