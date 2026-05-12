from dataclasses import dataclass
import json
import re
from typing import Iterable

import httpx
from django.conf import settings


@dataclass(frozen=True)
class AIAnalysis:
    summary: str
    category: str
    tags: list[str]
    provider: str


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
        response = httpx.post(
            f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=45,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
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
