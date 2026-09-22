"""Built-in keyword catalogs used by the deterministic stages.

Both catalogs are plain data: extend them from config (``extra_tools``) rather
than editing code.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

# canonical name -> (lower-case variants matched on word boundaries, category)
KNOWN_TOOLS: dict[str, tuple[list[str], str]] = {
    "ChatGPT": (["chatgpt", "chat gpt"], "llm"),
    "Claude": (["claude", "claude code"], "llm"),
    "Gemini": (["gemini"], "llm"),
    "Grok": (["grok"], "llm"),
    "DeepSeek": (["deepseek"], "llm"),
    "Mistral": (["mistral"], "llm"),
    "Llama": (["llama"], "llm"),
    "Perplexity": (["perplexity"], "llm"),
    "Ollama": (["ollama"], "llm"),
    "Cursor": (["cursor ide", "cursor editor", "in cursor", "cursor's", "cursor agent"], "coding"),
    "GitHub Copilot": (["copilot", "github copilot"], "coding"),
    "Windsurf": (["windsurf"], "coding"),
    "Replit": (["replit"], "coding"),
    "Bolt": (["bolt.new"], "coding"),
    "v0": (["v0.dev", "v0 by vercel"], "coding"),
    "Lovable": (["lovable"], "coding"),
    "LangChain": (["langchain"], "coding"),
    "LangGraph": (["langgraph"], "coding"),
    "Supabase": (["supabase"], "coding"),
    "Vercel": (["vercel"], "coding"),
    "n8n": (["n8n"], "automation"),
    "Make": (["make.com", "integromat"], "automation"),
    "Zapier": (["zapier"], "automation"),
    "CrewAI": (["crewai", "crew ai"], "automation"),
    "AutoGen": (["autogen"], "automation"),
    "Midjourney": (["midjourney"], "design"),
    "Figma": (["figma"], "design"),
    "Canva": (["canva"], "design"),
    "Runway": (["runway", "runwayml"], "media"),
    "ElevenLabs": (["elevenlabs", "eleven labs"], "media"),
    "Suno": (["suno"], "media"),
    "Whisper": (["whisper"], "media"),
    "Notion": (["notion"], "productivity"),
    "Obsidian": (["obsidian"], "productivity"),
    "Granola": (["granola"], "productivity"),
    "Pinecone": (["pinecone"], "data"),
    "Chroma": (["chromadb", "chroma db"], "data"),
    "Airtable": (["airtable"], "data"),
}

# topic -> keywords (matched on word boundaries, case-insensitive)
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "prompts": ["prompt", "prompts", "prompting", "system prompt", "few-shot", "zero-shot",
                "chain of thought", "instruction", "instructions", "template"],
    "agents": ["agent", "agents", "agentic", "autonomous", "multi-agent", "tool use",
               "function calling", "mcp", "subagent", "subagents"],
    "coding": ["code", "coding", "python", "javascript", "typescript", "programming",
               "developer", "github", "api", "sdk", "debug", "refactor", "repo", "repository"],
    "automation": ["automation", "automate", "automated", "workflow", "workflows", "pipeline",
                   "scraping", "scraper", "bot", "cron", "scheduler", "no-code", "low-code", "n8n",
                   "zapier"],
    "business": ["business", "startup", "saas", "revenue", "client", "clients", "customer",
                 "customers", "freelance", "agency", "pricing", "monetize", "sell", "income"],
    "marketing": ["marketing", "content", "audience", "brand", "copywriting", "seo", "ads",
                  "growth", "funnel", "newsletter", "leads"],
    "learning": ["learn", "learning", "course", "tutorial", "study", "skill", "skills",
                 "notes", "note-taking", "flashcards", "spaced repetition"],
    "productivity": ["productivity", "habit", "habits", "routine", "focus", "calendar",
                     "inbox", "meeting", "meetings", "second brain"],
    "design": ["design", "ui", "ux", "figma", "wireframe", "prototype", "typography",
               "landing page", "mockup"],
    "data": ["data", "dataset", "analytics", "dashboard", "rag", "embedding", "embeddings",
             "vector", "fine-tune", "fine-tuning", "retrieval"],
    "media": ["video", "podcast", "audio", "voice", "transcription", "thumbnail", "editing"],
}


def _pattern(variants: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![\w.])(?:{alts})(?![\w])", re.IGNORECASE)


@lru_cache(maxsize=512)
def compiled(variants: tuple[str, ...]) -> re.Pattern[str]:
    return _pattern(variants)


def tool_catalog(extra: dict[str, Any] | None = None) -> dict[str, tuple[list[str], str]]:
    """Return the built-in tool catalog merged with user-supplied tools.

    ``extra`` format: ``{"Name": {"variants": ["name"], "category": "coding"}}``.
    """
    cat = dict(KNOWN_TOOLS)
    for name, info in (extra or {}).items():
        info = info or {}
        variants = [str(v).lower() for v in (info.get("variants") or [str(name).lower()])]
        cat[str(name)] = (variants, str(info.get("category", "other")))
    return cat


def find_tools(text: str, extra: dict[str, Any] | None = None) -> dict[str, str]:
    """Return {tool name: category} for every catalog tool mentioned in ``text``."""
    found: dict[str, str] = {}
    for name, (variants, category) in tool_catalog(extra).items():
        if compiled(tuple(variants)).search(text or ""):
            found[name] = category
    return found
