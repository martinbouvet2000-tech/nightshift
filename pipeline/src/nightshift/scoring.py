"""Signal scoring: rate each item 0-100 to separate substance from noise.

signal = content density + concrete tools + linked repos + cross-author
recurrence - engagement-bait markers - thin content.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from nightshift.models import Item

HYPE_MARKERS = (
    "link in bio", "link in my bio", "comment below", "drop a comment", "comment the word",
    "dm me", "i'll send you", "i will send you", "follow for more", "like and subscribe",
    "smash that", "tag a friend", "limited time", "don't miss out", "100% guaranteed",
)
GITHUB_RE = re.compile(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.IGNORECASE)


def tool_recurrence(items: Iterable[Item],
                    existing: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """Map tool name -> set of distinct authors mentioning it (run + existing notes)."""
    rec: dict[str, set[str]] = {k: set(v) for k, v in (existing or {}).items()}
    for it in items:
        author = it.author or it.id
        for t in it.extraction.get("tools", []):
            rec.setdefault(t["name"], set()).add(author)
    return rec


def signal_score(item: Item, recurrence: dict[str, set[str]] | None = None) -> int:
    recurrence = recurrence or {}
    text = item.transcript or ""
    score = 30

    # 1. Content density
    n = len(text)
    if n > 2500:
        score += 22
    elif n > 800:
        score += 14
    elif n > 200:
        score += 6

    ext = item.extraction or {}
    tools = [t["name"] for t in ext.get("tools", [])]

    # 2. Concrete tools
    score += min(len(tools) * 4, 16)

    # 3. Linked repositories
    repos = set(GITHUB_RE.findall(text + " " + " ".join(ext.get("urls", []))))
    score += min(len(repos) * 3, 12)

    # 4. Actionable knowledge (techniques / prompts)
    score += min((len(ext.get("techniques", [])) + len(ext.get("prompts", []))) * 2, 10)

    # 5. Cross-author recurrence: a tool several creators talk about is a strong signal
    best = max((len(recurrence.get(t, set())) for t in tools), default=0)
    if best >= 4:
        score += 10
    elif best >= 2:
        score += 5

    # 6. Engagement bait / disguised ads
    low = f"{item.title}\n{text}".lower()
    hype = sum(1 for m in HYPE_MARKERS if m in low)
    score -= min(hype * 7, 21)

    # 7. Very thin content
    if n == 0 and len(item.title or "") < 80:
        score -= 12

    return max(0, min(100, score))
