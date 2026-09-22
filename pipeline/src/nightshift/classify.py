"""Topic classification by keyword density (deterministic)."""

from __future__ import annotations

from nightshift.catalog import CATEGORY_KEYWORDS, compiled
from nightshift.models import Item

DEFAULT_CATEGORY = "general"


def classify_text(text: str, keywords: dict[str, list[str]] | None = None, top: int = 3) -> list[str]:
    keywords = keywords or CATEGORY_KEYWORDS
    scores: dict[str, int] = {}
    for category, words in keywords.items():
        hits = len(compiled(tuple(w.lower() for w in words)).findall(text or ""))
        if hits:
            scores[category] = hits
    if not scores:
        return [DEFAULT_CATEGORY]
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [c for c, _ in ranked[:top]]


def classify(item: Item, top: int = 3) -> list[str]:
    return classify_text(f"{item.title}\n{item.transcript}", top=top)
