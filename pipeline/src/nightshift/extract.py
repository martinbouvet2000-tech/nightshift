"""Knowledge extraction: tools, prompts, techniques and ideas.

Two implementations share one output schema:
- ``regex_extract``: deterministic, offline, always available
- ``Extractor``: tries the configured LLM backend first (guarded by a circuit
  breaker) and falls back to ``regex_extract`` per item on any failure.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from nightshift.catalog import compiled, find_tools, tool_catalog
from nightshift.llm import Backend, CircuitBreaker, LLMError
from nightshift.models import Item

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“'])")
QUOTE_RE = re.compile(r"[\"“]([^\"”]{25,500})[\"”]")

TECHNIQUE_TRIGGERS = re.compile(
    r"\b(the trick is|the technique|this technique|technique (?:is|called)|here'?s how|"
    r"step (?:one|two|three|four|five|\d)|the workflow is|my workflow|pro tip|the key is|"
    r"what i do is|i call (?:it|this)|what i call|the pattern is|the method is)\b",
    re.IGNORECASE,
)
NAMED_TECHNIQUE = re.compile(
    r"\b(?:technique|method|pattern|approach|workflow) (?:called|named|is the) [\"“']?([A-Za-z0-9][\w\- ]{2,50}?)[\"”']?(?=[,.;:!?]|\s(?:and|which|that)\b)",
    re.IGNORECASE,
)
I_CALL_IT = re.compile(
    r"\b(?:i call (?:it|this)|what i call)\s+(?:the\s+|an?\s+)?[\"“']?([A-Za-z0-9][\w\- ]{2,50}?)[\"”']?(?=[,.;:!?]|$)",
    re.IGNORECASE)
IDEA_TRIGGERS = re.compile(
    r"\b(you could (?:build|sell|start|offer|charge|package|launch|turn)|business idea|"
    r"someone should build|there'?s (?:a|an|real) (?:business|opportunity|gap)|"
    r"opportunity (?:here|for)|startup idea|side project idea|side-project idea|"
    r"niche (?:service|product)|people would pay)\b",
    re.IGNORECASE,
)
IDEA_OFFER = re.compile(
    r"\b(?:you could|someone should|you can|people would pay)\b.*?\b(?:build|sell|start|offer|"
    r"charge|package|launch|turn|create|make)\b", re.IGNORECASE)
IDEA_PREFIX = re.compile(
    r"^.*?\b(?:you could|someone should|you can)\s+(?:build|sell|start|offer|package|launch|"
    r"create|make|turn)\s+(?:this\s+(?:as|into)\s+|it\s+(?:as|into)\s+)?(?:(?:a|an|the)\s+)?",
    re.IGNORECASE)
MONEY_OR_NUMBER = re.compile(r"(\$\s?\d|\d+\s?(?:%|percent|users|customers|hours|dollars|k\b))",
                             re.IGNORECASE)

MAX_ITEMS = {"tools": 15, "prompts": 8, "techniques": 8, "ideas": 5}

EXTRACTION_PROMPT = """You analyse the transcript of a video or talk about AI, tools, tech or business.

TITLE: {title}
AUTHOR: {author}
URL: {url}

TRANSCRIPT:
{transcript}

Return STRICT JSON only (no markdown fences, no commentary) with this shape:

{{
  "summary": "3-6 factual sentences: what is shown or said, concrete numbers/examples, steps in order if it is a tutorial",
  "tools": [{{"name": "tool name", "category": "llm|coding|automation|design|media|productivity|data|other", "description": "what it does concretely and how it is used in this content", "url": "url or null"}}],
  "prompts": [{{"title": "short title", "prompt": "the exact prompt, or a faithful reconstruction", "use_case": "when to use it"}}],
  "techniques": [{{"name": "short name", "description": "concrete steps, not a vague concept"}}],
  "ideas": [{{"title": "45-75 character noun phrase: offer + audience, no trailing punctuation", "idea": "one sentence", "potential": "why it could work, with numbers from the content if any", "action": "one concrete first step"}}]
}}

Rules:
- Only include what is clearly present in the content. Never invent.
- Empty category = empty list [].
- Ideas only when genuinely actionable.
"""


# ─── helpers ────────────────────────────────────────────────────────────────

def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s.strip()]


def _clip(s: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _short_title(sentence: str, max_words: int = 9, max_len: int = 70) -> str:
    s = re.sub(r"^(so|and|but|okay|ok|now|also|well)[, ]+", "", sentence.strip(), flags=re.I)
    s = re.sub(r"[\"“”]", "", s)
    words = re.findall(r"[\w$%'’-]+", s)
    title = " ".join(words[:max_words])
    title = title[:1].upper() + title[1:]
    return _clip(title, max_len).rstrip(" .,;:")


def idea_title(sentence: str) -> str:
    """Turn "You could build a X for Y, ..." into "X for Y"."""
    core = IDEA_PREFIX.sub("", sentence.strip(), count=1)
    core = re.split(r"[,;:]| which | that | who | because | but ", core, maxsplit=1)[0]
    if len(core.split()) < 3:
        core = sentence
    return _short_title(core, 11, 75)


def empty_extraction() -> dict[str, Any]:
    return {"summary": "", "tools": [], "prompts": [], "techniques": [], "ideas": [], "urls": []}


# ─── deterministic extractor ────────────────────────────────────────────────

def regex_extract(item: Item, extra_tools: dict[str, Any] | None = None) -> dict[str, Any]:
    """Heuristic extraction that needs no network and no model."""
    text = f"{item.title}\n{item.transcript}"
    sentences = split_sentences(item.transcript)
    out = empty_extraction()

    out["summary"] = _clip(" ".join(sentences[:3]), 600)

    # Tools: catalog match + first sentence mentioning the tool as description.
    catalog = tool_catalog(extra_tools)
    for name, category in find_tools(text, extra_tools).items():
        desc = ""
        pattern = compiled(tuple(catalog[name][0]))
        for s in sentences:
            if pattern.search(s):
                desc = _clip(s, 260)
                break
        out["tools"].append({"name": name, "category": category, "description": desc, "url": None})

    # URLs
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:")
        if u not in out["urls"]:
            out["urls"].append(u)

    # Prompts: quoted text in (or right after) a sentence that talks about prompts.
    seen_prompts: set[str] = set()
    for i, s in enumerate(sentences):
        if "prompt" not in s.lower():
            continue
        window = " ".join(sentences[i:i + 2])
        for q in QUOTE_RE.findall(window):
            key = q.lower().strip()
            if key in seen_prompts:
                continue
            seen_prompts.add(key)
            out["prompts"].append({
                "title": _short_title(q, 6, 60),
                "prompt": _clip(q, 500),
                "use_case": _clip(s if q not in s else "", 200),
            })

    # Techniques
    seen_tech: set[str] = set()
    for i, s in enumerate(sentences):
        if not (TECHNIQUE_TRIGGERS.search(s) or NAMED_TECHNIQUE.search(s) or I_CALL_IT.search(s)):
            continue
        named = NAMED_TECHNIQUE.search(s) or I_CALL_IT.search(s)
        name = named.group(1).strip().title() if named else _short_title(s, 7, 60)
        if name.lower() in seen_tech:
            continue
        seen_tech.add(name.lower())
        desc = " ".join(sentences[i:i + 2])
        out["techniques"].append({"name": name, "description": _clip(desc, 400)})

    # Ideas
    seen_ideas: set[str] = set()
    used: set[int] = set()
    for i, s in enumerate(sentences):
        if i in used or not IDEA_TRIGGERS.search(s):
            continue
        j = i
        # "Here is a business idea." is a lead-in: the idea is the next sentence.
        if not IDEA_OFFER.search(s) and i + 1 < len(sentences) and IDEA_OFFER.search(sentences[i + 1]):
            j = i + 1
        used.update({i, j})
        s = sentences[j]
        title = idea_title(s)
        if title.lower() in seen_ideas:
            continue
        seen_ideas.add(title.lower())
        nxt = sentences[j + 1] if j + 1 < len(sentences) else ""
        potential = nxt if MONEY_OR_NUMBER.search(nxt) else ""
        out["ideas"].append({
            "title": title,
            "idea": _clip(s, 300),
            "potential": _clip(potential, 300),
            "action": "Talk to five people in the target audience before building anything.",
        })

    return normalize_extraction(out)


# ─── LLM output handling ────────────────────────────────────────────────────

def build_prompt(item: Item, max_chars: int = 40000) -> str:
    t = item.transcript or "(no transcript available; analyse the title only)"
    if len(t) > max_chars:
        t = t[:max_chars] + " [...transcript truncated]"
    return EXTRACTION_PROMPT.format(title=item.title or "(untitled)",
                                    author=item.author or "unknown",
                                    url=item.url or "n/a", transcript=t)


def parse_llm_json(raw: str | None) -> dict[str, Any] | None:
    """Parse a model reply into a dict, tolerating code fences and chatter."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE | re.MULTILINE).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(s[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dict_list(value: Any, keys: tuple[str, ...], limits: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    if not isinstance(value, list):
        return out
    for entry in value:
        if not isinstance(entry, dict):
            continue
        clean = {k: _clip(entry.get(k), limits.get(k, 400)) for k in keys}
        if any(clean.values()):
            out.append(clean)
    return out


def normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce any extractor output into the canonical schema with sane limits."""
    out = empty_extraction()
    out["summary"] = _clip(data.get("summary"), 1500)
    tools = _dict_list(data.get("tools"), ("name", "category", "description", "url"),
                       {"name": 60, "category": 30, "description": 400, "url": 300})
    for t in tools:
        t["url"] = t["url"] if t["url"].startswith(("http://", "https://")) else None
        t["category"] = (t["category"] or "other").lower()
    out["tools"] = [t for t in tools if t["name"]][: MAX_ITEMS["tools"]]
    out["prompts"] = [p for p in _dict_list(data.get("prompts"), ("title", "prompt", "use_case"),
                                           {"title": 80, "prompt": 1500, "use_case": 300})
                      if p["prompt"]][: MAX_ITEMS["prompts"]]
    out["techniques"] = [t for t in _dict_list(data.get("techniques"), ("name", "description"),
                                              {"name": 80, "description": 800})
                         if t["name"]][: MAX_ITEMS["techniques"]]
    out["ideas"] = [i for i in _dict_list(data.get("ideas"), ("title", "idea", "potential", "action"),
                                         {"title": 90, "idea": 400, "potential": 400, "action": 300})
                    if i["title"] or i["idea"]][: MAX_ITEMS["ideas"]]
    for idea in out["ideas"]:
        if not idea["title"]:
            idea["title"] = _short_title(idea["idea"], 10, 75)
    urls = data.get("urls") if isinstance(data.get("urls"), list) else []
    out["urls"] = [str(u) for u in urls if str(u).startswith(("http://", "https://"))][:20]
    return out


class Extractor:
    """LLM-first extractor with per-item regex fallback and a circuit breaker."""

    def __init__(self, backend: Backend | None, breaker: CircuitBreaker | None = None,
                 extra_tools: dict[str, Any] | None = None, max_chars: int = 40000):
        self.backend = backend
        self.breaker = breaker or CircuitBreaker()
        self.extra_tools = extra_tools or {}
        self.max_chars = max_chars
        self.llm_calls = 0

    def extract(self, item: Item) -> tuple[dict[str, Any], str]:
        regex = regex_extract(item, self.extra_tools)
        if self.backend is None or not self.breaker.allow():
            return regex, "regex"
        self.llm_calls += 1
        try:
            raw = self.backend.complete(build_prompt(item, self.max_chars))
            data = parse_llm_json(raw)
            if data is None:
                raise LLMError("unparseable JSON reply")
        except Exception as exc:  # any backend failure -> regex for this item
            self.breaker.record_failure()
            log.warning("LLM extraction failed for %s (%s); using regex", item.id, exc)
            return regex, "regex"
        self.breaker.record_success()
        result = normalize_extraction(data)
        # Keep catalog tools the model missed, and URLs found deterministically.
        have = {t["name"].lower() for t in result["tools"]}
        for t in regex["tools"]:
            if t["name"].lower() not in have:
                result["tools"].append(t)
        result["urls"] = list(dict.fromkeys(result["urls"] + regex["urls"]))
        if not result["summary"]:
            result["summary"] = regex["summary"]
        return result, self.backend.name
