"""Related-note linking by shared topics, author and content keywords."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

STOPWORDS = {
    "about", "after", "again", "being", "could", "every", "first", "going", "great",
    "their", "there", "these", "thing", "things", "those", "three", "today", "really",
    "which", "would", "should", "where", "while", "other", "under", "video", "right",
    "because", "actually", "people", "something", "basically", "gonna", "wanna", "little",
    "maybe", "still", "might", "doing", "making", "means", "never", "since", "start",
    "using", "without", "works", "whole", "https", "yourself", "before", "better", "different",
}
TAG_WEIGHT = 2.0
AUTHOR_WEIGHT = 1.0
KEYWORD_WEIGHT = 1.0
MAX_SAME_AUTHOR = 3


def top_keywords(text: str, n: int = 25) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z-]{4,}", (text or "").lower()) if w not in STOPWORDS]
    return [w for w, _ in Counter(words).most_common(n)]


@dataclass
class NoteRef:
    stem: str
    topics: set[str] = field(default_factory=set)
    author: str = ""
    keywords: set[str] = field(default_factory=set)


def similarity(a: NoteRef, b: NoteRef) -> tuple[float, set[str]]:
    shared = a.topics & b.topics
    score = len(shared) * TAG_WEIGHT
    if a.author and a.author == b.author:
        score += AUTHOR_WEIGHT
    if a.keywords and b.keywords:
        score += min(len(a.keywords & b.keywords) / 5, 2.0) * KEYWORD_WEIGHT
    return score, shared


def related(note: NoteRef, corpus: list[NoteRef], max_links: int = 6,
            min_score: float = 2.0) -> list[tuple[str, str]]:
    """Return [(stem, reason)] for the most related notes in ``corpus``."""
    scored = []
    for other in corpus:
        if other.stem == note.stem:
            continue
        s, shared = similarity(note, other)
        if s >= min_score:
            scored.append((s, other, shared))
    scored.sort(key=lambda x: (-x[0], x[1].stem))
    out: list[tuple[str, str]] = []
    same_author = 0
    for s, other, shared in scored:
        if note.author and other.author == note.author:
            if same_author >= MAX_SAME_AUTHOR:
                continue
            same_author += 1
        if shared:
            reason = "shared topics: " + ", ".join(sorted(shared))
        elif note.author and other.author == note.author:
            reason = "same author"
        else:
            reason = "similar content"
        out.append((other.stem, reason))
        if len(out) >= max_links:
            break
    return out
