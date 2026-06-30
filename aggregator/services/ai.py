from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
import re
from typing import Iterable

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from aggregator.models import AIUsageDaily


@dataclass(frozen=True)
class AIAnalysis:
    summary: str
    category: str
    tags: list[str]
    provider: str


@dataclass(frozen=True)
class DeepSeekBudgetReservation:
    usage_date: object
    provider: str
    model: str
    estimated_cost_cny: Decimal


class BaseAIProvider:
    provider_name = "base"

    def analyze(self, text: str, categories: Iterable[str]) -> AIAnalysis:
        raise NotImplementedError


class RuleBasedAIProvider(BaseAIProvider):
    provider_name = "rules"
    keyword_map = {
        "招生": ["招生", "录取", "复试", "考生", "研究生", "本科"],
        "科研": ["科研", "实验室", "论文", "项目", "基金", "学术"],
        "就业": ["就业", "招聘", "宣讲", "实习"],
        "社团": ["社团", "活动", "比赛", "志愿"],
        "通知": ["通知", "安排", "公告", "公示"],
    }

    def analyze(self, text: str, categories: Iterable[str]) -> AIAnalysis:
        clean_text = re.sub(r"\s+", " ", text or "").strip()
        available = list(categories) or list(self.keyword_map)
        scores = {category: 0 for category in available}
        for category in available:
            for keyword in self.keyword_map.get(category, [category]):
                if keyword in clean_text:
                    scores[category] += 1
        category = max(scores, key=scores.get) if scores else "通知"
        if scores and scores[category] == 0:
            category = available[0]
        tags = []
        for keywords in self.keyword_map.values():
            for keyword in keywords:
                if keyword in clean_text and keyword not in tags:
                    tags.append(keyword)
                if len(tags) >= 6:
                    break
            if len(tags) >= 6:
                break
        summary = clean_text[:160]
        return AIAnalysis(summary=summary, category=category, tags=tags, provider=self.provider_name)


class DeepSeekAIProvider(BaseAIProvider):
    provider_name = "deepseek"

    def analyze(self, text: str, categories: Iterable[str]) -> AIAnalysis:
        if not settings.DEEPSEEK_API_KEY:
            return RuleBasedAIProvider().analyze(text, categories)
        categories_list = list(categories)
        prompt = (
            "你是高校信息聚合网站的内容编辑。请根据正文输出 JSON，字段为 "
            "summary、category、tags。category 必须从候选分类中选择。"
            f"候选分类：{categories_list}\n正文：{text[:6000]}"
        )
        max_tokens = settings.DEEPSEEK_MAX_OUTPUT_TOKENS
        reservation = reserve_deepseek_budget(
            settings.DEEPSEEK_MODEL,
            estimated_prompt_tokens=_estimate_prompt_tokens(prompt),
            estimated_completion_tokens=max_tokens,
        )
        if reservation is None:
            return RuleBasedAIProvider().analyze(text, categories_list)

        finalized = False
        try:
            response = httpx.post(
                f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                json={
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                },
                timeout=45,
            )
            response.raise_for_status()
            response_payload = response.json()
            usage = response_payload.get("usage", {})
            finalize_deepseek_budget(reservation, usage)
            finalized = True
            content = response_payload["choices"][0]["message"]["content"]
            payload = json.loads(content)
            category = payload.get("category") or (categories_list[0] if categories_list else "通知")
            if categories_list and category not in categories_list:
                category = categories_list[0]
            return AIAnalysis(
                summary=str(payload.get("summary", ""))[:500],
                category=category,
                tags=[str(tag)[:60] for tag in payload.get("tags", [])[:8]],
                provider=self.provider_name,
            )
        except Exception:
            if not finalized:
                release_deepseek_budget(reservation)
            return RuleBasedAIProvider().analyze(text, categories_list)


class OllamaAIProvider(BaseAIProvider):
    provider_name = "ollama"

    def analyze(self, text: str, categories: Iterable[str]) -> AIAnalysis:
        categories_list = list(categories)
        prompt = (
            "只输出 JSON，字段为 summary、category、tags。"
            f"category 从这些分类选择：{categories_list}\n{text[:4000]}"
        )
        response = httpx.post(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "format": "json", "stream": False},
            timeout=90,
        )
        response.raise_for_status()
        payload = json.loads(response.json().get("response", "{}"))
        category = payload.get("category") or (categories_list[0] if categories_list else "通知")
        if categories_list and category not in categories_list:
            category = categories_list[0]
        return AIAnalysis(
            summary=str(payload.get("summary", ""))[:500],
            category=category,
            tags=[str(tag)[:60] for tag in payload.get("tags", [])[:8]],
            provider=self.provider_name,
        )


def get_ai_provider() -> BaseAIProvider:
    provider = settings.AI_PROVIDER.lower()
    if provider == "deepseek":
        return DeepSeekAIProvider()
    if provider == "ollama":
        return OllamaAIProvider()
    return RuleBasedAIProvider()


def reserve_deepseek_budget(
    model: str,
    estimated_prompt_tokens: int,
    estimated_completion_tokens: int,
) -> DeepSeekBudgetReservation | None:
    usage_date = timezone.localdate()
    budget_cny = _decimal_setting("DEEPSEEK_DAILY_BUDGET_CNY")
    estimated_cost_cny = _estimate_cost_cny(
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=estimated_prompt_tokens,
        completion_tokens=estimated_completion_tokens,
    )
    with transaction.atomic():
        usage, _ = AIUsageDaily.objects.select_for_update().get_or_create(
            usage_date=usage_date,
            provider="deepseek",
            model=model,
        )
        if usage.cost_cny + estimated_cost_cny > budget_cny:
            return None
        usage.estimated_prompt_tokens += estimated_prompt_tokens
        usage.estimated_completion_tokens += estimated_completion_tokens
        usage.cost_cny += estimated_cost_cny
        usage.save(
            update_fields=[
                "estimated_prompt_tokens",
                "estimated_completion_tokens",
                "cost_cny",
                "updated_at",
            ]
        )
    return DeepSeekBudgetReservation(usage_date, "deepseek", model, estimated_cost_cny)


def finalize_deepseek_budget(reservation: DeepSeekBudgetReservation, usage_payload: dict) -> None:
    prompt_cache_hit_tokens = int(usage_payload.get("prompt_cache_hit_tokens") or 0)
    prompt_cache_miss_tokens = int(usage_payload.get("prompt_cache_miss_tokens") or 0)
    if prompt_cache_hit_tokens == 0 and prompt_cache_miss_tokens == 0:
        prompt_cache_miss_tokens = int(usage_payload.get("prompt_tokens") or 0)
    completion_tokens = int(usage_payload.get("completion_tokens") or 0)
    actual_cost_cny = _estimate_cost_cny(
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        completion_tokens=completion_tokens,
    )
    with transaction.atomic():
        usage = AIUsageDaily.objects.select_for_update().get(
            usage_date=reservation.usage_date,
            provider=reservation.provider,
            model=reservation.model,
        )
        usage.request_count += 1
        usage.prompt_cache_hit_tokens += prompt_cache_hit_tokens
        usage.prompt_cache_miss_tokens += prompt_cache_miss_tokens
        usage.completion_tokens += completion_tokens
        usage.cost_cny = max(Decimal("0"), usage.cost_cny - reservation.estimated_cost_cny + actual_cost_cny)
        usage.save(
            update_fields=[
                "request_count",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
                "completion_tokens",
                "cost_cny",
                "updated_at",
            ]
        )


def release_deepseek_budget(reservation: DeepSeekBudgetReservation) -> None:
    with transaction.atomic():
        usage = AIUsageDaily.objects.select_for_update().get(
            usage_date=reservation.usage_date,
            provider=reservation.provider,
            model=reservation.model,
        )
        usage.cost_cny = max(Decimal("0"), usage.cost_cny - reservation.estimated_cost_cny)
        usage.save(update_fields=["cost_cny", "updated_at"])


def _estimate_prompt_tokens(prompt: str) -> int:
    return max(1, len(prompt or ""))


def _estimate_cost_cny(
    prompt_cache_hit_tokens: int,
    prompt_cache_miss_tokens: int,
    completion_tokens: int,
) -> Decimal:
    usd = (
        Decimal(prompt_cache_hit_tokens) * _decimal_setting("DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION")
        + Decimal(prompt_cache_miss_tokens) * _decimal_setting("DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION")
        + Decimal(completion_tokens) * _decimal_setting("DEEPSEEK_OUTPUT_USD_PER_MILLION")
    ) / Decimal("1000000")
    return (usd * _decimal_setting("DEEPSEEK_USD_TO_CNY")).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def _decimal_setting(name: str) -> Decimal:
    return Decimal(str(getattr(settings, name)))
