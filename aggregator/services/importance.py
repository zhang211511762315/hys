from datetime import datetime

from django.utils import timezone

from aggregator.models import Source

IMPORTANT_KEYWORDS = {
    "通知": 16,
    "公告": 14,
    "公示": 18,
    "招生": 18,
    "招聘": 18,
    "就业": 16,
    "报名": 14,
    "截止": 16,
    "复试": 18,
    "考试": 14,
    "资格": 14,
    "安排": 10,
    "实验室": 8,
    "科研": 8,
    "竞赛": 6,
}


def score_importance(
    source: Source,
    title: str,
    text: str,
    category_name: str = "",
    published_at: datetime | None = None,
) -> int:
    score = 0
    if source.priority == Source.Priority.HIGH:
        score += 25
    elif source.priority == Source.Priority.NORMAL:
        score += 12
    if source.source_type == Source.SourceType.OFFICIAL_SITE:
        score += 20
    elif source.source_type == Source.SourceType.DEPARTMENT_SITE:
        score += 14
    elif source.source_type == Source.SourceType.COLLEGE_SITE:
        score += 10
    combined = f"{title}\n{category_name}\n{text[:1000]}"
    for keyword, weight in IMPORTANT_KEYWORDS.items():
        if keyword in combined:
            score += weight
    if published_at:
        age_days = (timezone.now() - published_at).days
        if age_days > 730:
            score -= 45
        elif age_days > 365:
            score -= 25
        elif age_days > 180:
            score -= 10
    return max(0, min(score, 100))
