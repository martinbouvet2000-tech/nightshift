"""User profile and idea-fit scoring.

The profile is a small YAML/JSON file the user fills in (see
``profile.example.yaml``). Each extracted idea gets a 0-100 fit score and a
verdict, computed deterministically so it is explainable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

TEAM_WORDS = re.compile(r"\b(hire|hiring|team of|employees|staff|co-?founders?|sales team)\b", re.I)
FULLTIME_WORDS = re.compile(r"\b(full[- ]time|24/7|around the clock)\b", re.I)
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m)?\b", re.I)

VERDICTS = ((70, "strong fit"), (50, "worth exploring"), (30, "weak fit"), (0, "skip"))


@dataclass
class Profile:
    name: str = "default"
    interests: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    solo: bool = True
    max_budget_usd: float | None = None
    hours_per_week: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        c = d.get("constraints") or {}
        def _list(key: str) -> list[str]:
            return [str(x).strip().lower() for x in (d.get(key) or []) if str(x).strip()]
        return cls(
            name=str(d.get("name") or "default"),
            interests=_list("interests"),
            skills=_list("skills"),
            avoid=_list("avoid"),
            solo=bool(c.get("solo", True)),
            max_budget_usd=float(c["max_budget_usd"]) if c.get("max_budget_usd") is not None else None,
            hours_per_week=float(c["hours_per_week"]) if c.get("hours_per_week") is not None else None,
        )


def load_profile(path: str | None) -> Profile:
    if not path:
        return Profile()
    p = Path(path)
    if not p.exists():
        log.warning("profile file not found (%s); using an empty profile", p)
        return Profile()
    text = p.read_text(encoding="utf-8")
    data = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    return Profile.from_dict(data or {})


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9+#.-]*", text.lower()))


def _match(phrase: str, text: str, words: set[str]) -> float:
    """1.0 for a full phrase match, 0.5 when a significant word of it matches."""
    if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text):
        return 1.0
    sig = [w for w in re.findall(r"[a-z0-9+#-]+", phrase) if len(w) >= 5]
    return 0.5 if any(w in words for w in sig) else 0.0


def _max_amount(text: str) -> float:
    best = 0.0
    for num, suffix in MONEY.findall(text):
        v = float(num.replace(",", ""))
        v *= {"k": 1e3, "m": 1e6}.get(suffix.lower(), 1) if suffix else 1
        best = max(best, v)
    return best


def score_idea(idea: dict[str, Any], profile: Profile) -> tuple[int, str, list[str]]:
    """Return (fit score 0-100, verdict, human-readable reasons)."""
    text = " ".join(str(idea.get(k, "")) for k in ("title", "idea", "potential", "action")).lower()
    words = _words(text)
    score = 35.0
    reasons: list[str] = []

    interest = sum(_match(p, text, words) for p in profile.interests)
    if interest:
        score += min(interest * 15, 45)
        reasons.append(f"matches interests (+{min(interest * 15, 45):.0f})")
    skill = sum(_match(p, text, words) for p in profile.skills)
    if skill:
        score += min(skill * 10, 20)
        reasons.append(f"uses your skills (+{min(skill * 10, 20):.0f})")
    for p in profile.avoid:
        if _match(p, text, words) >= 1.0:
            score -= 30
            reasons.append(f"mentions '{p}' from your avoid list (-30)")
    if profile.solo and TEAM_WORDS.search(text):
        score -= 10
        reasons.append("seems to need a team (-10)")
    if profile.max_budget_usd is not None:
        amount = _max_amount(text)
        if amount > profile.max_budget_usd:
            score -= 10
            reasons.append("cost mention above budget (-10)")
    if profile.hours_per_week is not None and profile.hours_per_week < 20 and FULLTIME_WORDS.search(text):
        score -= 10
        reasons.append("looks full-time (-10)")

    final = int(round(max(0, min(100, score))))
    verdict = next(label for threshold, label in VERDICTS if final >= threshold)
    if not reasons:
        reasons.append("no profile signal either way")
    return final, verdict, reasons
