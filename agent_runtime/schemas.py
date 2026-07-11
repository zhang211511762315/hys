from decimal import Decimal

from pydantic import BaseModel, Field


class CitationSchema(BaseModel):
    title: str
    source: str
    url: str
    snippet: str = ""


class RagAnswerSchema(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[CitationSchema] = Field(default_factory=list)
    model: str


class UsageReportSchema(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_cny: Decimal = Field(ge=0)
    budget_remaining_cny: Decimal = Field(ge=0)
    status: str


class SelfHealPlanSchema(BaseModel):
    dry_run: bool
    actions: list[str] = Field(default_factory=list)
    consumes_llm_budget: bool = False
