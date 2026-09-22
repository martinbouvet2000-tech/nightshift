"""Markdown renderers for source, tool, idea and digest notes."""

from __future__ import annotations

from typing import Any

from nightshift.fsutil import sanitize_filename
from nightshift.models import Item
from nightshift.writer import VaultWriter, neutralize_links

SOURCES, TOOLS, IDEAS, DIGEST = "sources", "tools", "ideas", "digest"


def tool_stem(name: str) -> str:
    return sanitize_filename(name, max_len=80)


def idea_stem(title: str) -> str:
    return sanitize_filename(title, max_len=90)


def source_meta(item: Item) -> dict[str, Any]:
    return {
        "tags": ["source", item.source, *item.categories],
        "type": "source",
        "source": item.source,
        "score": item.signal_score,
        "title": item.title,
        "author": item.author,
        "url": item.url,
        "published": item.published or None,
        "source_id": item.id,
        "backend": item.backend,
        "topics": list(item.categories),
        "keywords": item.keywords[:15],
    }


def render_source(item: Item, w: VaultWriter, ideas: list[dict[str, Any]],
                  related: list[tuple[str, str]] | None = None) -> str:
    ext = item.extraction
    t = neutralize_links
    out: list[str] = []

    facts = [f"**Source:** {item.source}"]
    if item.author:
        facts.append(f"**Author:** {t(item.author)}")
    if item.published:
        facts.append(f"**Published:** {item.published}")
    if item.url:
        facts.append(f"[Original]({item.url})")
    facts.append(f"**Signal:** {item.signal_score}/100")
    out.append(" · ".join(facts))

    out.append("## Summary\n\n" + (t(ext.get("summary")) or "_No summary available._"))

    if ext.get("tools"):
        lines = []
        for tool in ext["tools"]:
            link = w.link(TOOLS, tool_stem(tool["name"]))
            desc = f" — {t(tool['description'])}" if tool.get("description") else ""
            lines.append(f"- {link} ({tool.get('category') or 'other'}){desc}")
        out.append("## Tools\n\n" + "\n".join(lines))

    if ext.get("techniques"):
        blocks = [f"### {t(x['name'])}\n\n{t(x['description'])}" for x in ext["techniques"]]
        out.append("## Techniques\n\n" + "\n\n".join(blocks))

    if ext.get("prompts"):
        blocks = []
        for p in ext["prompts"]:
            body = p["prompt"].replace("```", "'''")
            use = f"\n\n*Use case:* {t(p['use_case'])}" if p.get("use_case") else ""
            blocks.append(f"### {t(p['title'] or 'Prompt')}\n\n```text\n{body}\n```{use}")
        out.append("## Prompts\n\n" + "\n\n".join(blocks))

    if ideas:
        lines = []
        for idea in ideas:
            link = w.link(IDEAS, idea_stem(idea["title"]))
            lines.append(f"- {link} — fit {idea['fit_score']}/100 ({idea['verdict']})")
        out.append("## Ideas\n\n" + "\n".join(lines))

    if ext.get("urls"):
        out.append("## Links\n\n" + "\n".join(f"- <{u}>" for u in ext["urls"]))

    if related:
        lines = [f"- {w.link(SOURCES, stem)} — {reason}" for stem, reason in related]
        out.append("## Related\n\n" + "\n".join(lines))

    if item.transcript:
        out.append("## Transcript\n\n" + t(item.transcript))
    return "\n\n".join(out)


def render_tool(name: str, meta: dict[str, Any], w: VaultWriter) -> str:
    out = [f"**Category:** {meta.get('category') or 'other'}"]
    if meta.get("url"):
        out[0] += f" · [Website]({meta['url']})"
    if meta.get("description"):
        out.append(neutralize_links(meta["description"]))
    mentions = [m for m in meta.get("mentions", []) if w.exists(SOURCES, m)]
    if mentions:
        out.append("## Mentions\n\n" + "\n".join(f"- {w.link(SOURCES, m)}" for m in mentions))
    authors = meta.get("authors") or []
    if authors:
        out.append(f"Mentioned by {len(authors)} distinct creator(s).")
    return "\n\n".join(out)


def render_idea(idea: dict[str, Any], origin_stem: str, w: VaultWriter) -> str:
    t = neutralize_links
    out = [f"**Idea:** {t(idea.get('idea') or idea['title'])}"]
    if idea.get("potential"):
        out.append("## Why it could work\n\n" + t(idea["potential"]))
    if idea.get("action"):
        out.append("## First step\n\n" + t(idea["action"]))
    reasons = "\n".join(f"- {t(r)}" for r in idea.get("reasons", []))
    out.append(f"## Profile fit\n\n**{idea['fit_score']}/100 — {idea['verdict']}**\n\n{reasons}")
    out.append(f"## Origin\n\n{w.link(SOURCES, origin_stem)}")
    return "\n\n".join(out)
