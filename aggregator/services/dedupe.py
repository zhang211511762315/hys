import hashlib
import re
from difflib import SequenceMatcher

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text or "").strip()


def content_fingerprint(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def similarity(left: str, right: str) -> float:
    left_key = _PUNCT_RE.sub("", normalize_text(left).lower())
    right_key = _PUNCT_RE.sub("", normalize_text(right).lower())
    if not left_key or not right_key:
        return 0.0
    return SequenceMatcher(None, left_key, right_key).ratio()


def is_near_duplicate(left: str, right: str, threshold: float = 0.82) -> bool:
    return similarity(left, right) >= threshold
