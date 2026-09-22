"""Pipeline orchestrator.

Stages (each item is isolated: one failure never aborts the run):
    1. collect     sources yield items (skipping already-synced IDs)
    2. transcribe  media without transcript -> Whisper (optional) or skipped
    3. classify    topic categories by keyword density
    4. extract     tools / prompts / techniques / ideas (LLM chain -> regex)
    5. score       0-100 signal score (density, tools, repos, recurrence, hype)
    6. fit         idea scoring against the user profile
    7. write       source notes, then tool notes and idea notes
    8. link        related-notes section, links resolved against existing notes
    9. digest      daily digest note
   10. state       mark written items as done
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from nightshift.classify import classify
from nightshift.digest import build_digest
from nightshift.extract import Extractor
from nightshift.fsutil import sanitize_filename
from nightshift.linking import NoteRef, related, top_keywords
from nightshift.llm import CircuitBreaker, select_backend
from nightshift.models import Item
from nightshift.notes import (IDEAS, SOURCES, TOOLS, idea_stem, render_idea, render_source,
                              render_tool, source_meta, tool_stem)
from nightshift.profile import Profile, load_profile, score_idea
from nightshift.scoring import signal_score, tool_recurrence
from nightshift.sources import SOURCES as SOURCE_REGISTRY
from nightshift.sources import StateStore
from nightshift.transcribe import transcribe_media
from nightshift.writer import VaultWriter

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    vault: str
    dry_run: bool = False
    backend: str = "regex"
    collected: int = 0
    processed: int = 0
    skipped: int = 0
    errors: list[tuple[str, str, str]] = field(default_factory=list)
    notes: Counter = field(default_factory=Counter)
    backends_used: Counter = field(default_factory=Counter)
    llm_calls: int = 0
    breaker_open: bool = False
    digest: str | None = None
    top: list[tuple[int, str]] = field(default_factory=list)
    ideas: list[tuple[int, str, str]] = field(default_factory=list)
    duration: float = 0.0

    def error(self, item_id: str, stage: str, exc: BaseException | str) -> None:
        msg = str(exc)[:200]
        self.errors.append((item_id, stage, msg))
        log.warning("[%s] %s: %s", stage, item_id, msg)

    def format(self) -> str:
        mode = " (dry run: nothing written)" if self.dry_run else ""
        lines = [
            f"nightshift run complete{mode} in {self.duration:.1f}s",
            f"  vault:     {self.vault}",
            f"  backend:   {self.backend} (LLM calls: {self.llm_calls}, circuit breaker: "
            f"{'OPEN' if self.breaker_open else 'closed'})",
            f"  items:     {self.collected} collected, {self.processed} processed, "
            f"{self.skipped} skipped, {len(self.errors)} error(s)",
            "  notes:     " + ", ".join(f"{self.notes[k]} {k}" for k in
                                        ("sources", "tools", "ideas", "digest")),
        ]
        if self.top:
            lines.append("  top signal:")
            lines += [f"    {s:>3}  {stem}" for s, stem in self.top[:5]]
        if self.ideas:
            lines.append("  ideas by profile fit:")
            lines += [f"    {s:>3}  {v:<16} {t}" for s, v, t in self.ideas[:5]]
        if self.digest:
            lines.append(f"  digest:    {self.digest}")
        for item_id, stage, msg in self.errors[:10]:
            lines.append(f"  ! {stage} {item_id}: {msg}")
        return "\n".join(lines)


def build_sources(cfg: dict[str, Any], state: StateStore, only: list[str] | None = None):
    out = []
    for name, cls in SOURCE_REGISTRY.items():
        scfg = (cfg.get("sources") or {}).get(name) or {}
        if only is not None:
            if name not in only:
                continue
        elif not scfg.get("enabled"):
            continue
        out.append(cls(scfg, state))
    if only:
        unknown = set(only) - set(SOURCE_REGISTRY)
        for u in sorted(unknown):
            log.warning("unknown source %r (available: %s)", u, ", ".join(SOURCE_REGISTRY))
    return out


def resolve_source_stem(w: VaultWriter, item: Item) -> str:
    base = sanitize_filename(item.title or item.id, max_len=90)
    candidates = [base] + [sanitize_filename(f"{base} {item.id[-8:]}", max_len=100)] + [
        sanitize_filename(f"{base} {item.id[-8:]} {n}", max_len=100) for n in range(2, 50)]
    for stem in candidates:
        if not w.exists(SOURCES, stem):
            return stem
        meta, _ = w.read(SOURCES, stem)
        if meta.get("source_id") == item.id:
            return stem
    raise ValueError("could not find a free note name")


def _note_ref(stem: str, meta: dict[str, Any]) -> NoteRef:
    return NoteRef(stem=stem, topics=set(meta.get("topics") or []),
                   author=str(meta.get("author") or ""),
                   keywords=set(meta.get("keywords") or []))


def run_pipeline(cfg: dict[str, Any], only_sources: list[str] | None = None,
                 dry_run: bool = False, limit: int | None = None,
                 backend_override: str | None = None, today: date | None = None,
                 profile: Profile | None = None) -> RunSummary:
    t0 = time.monotonic()
    if not cfg.get("vault_path"):
        raise ValueError("no vault configured: set NIGHTSHIFT_VAULT or vault_path in the config")
    vault = Path(cfg["vault_path"])
    summary = RunSummary(vault=str(vault), dry_run=dry_run)

    state = StateStore(Path(cfg["state_dir"]) / "state.json" if cfg.get("state_dir") else None)
    w = VaultWriter(vault, cfg["folders"], dry_run=dry_run, today=today)
    profile = profile or load_profile(cfg.get("profile_path"))
    llm_cfg = dict(cfg.get("llm") or {})
    if backend_override:
        llm_cfg["backend"] = backend_override
    backend = select_backend(llm_cfg)
    summary.backend = backend.name if backend else "regex"
    extractor = Extractor(backend, CircuitBreaker(llm_cfg.get("circuit_breaker_threshold", 5)),
                          cfg.get("extra_tools"), int(llm_cfg.get("max_transcript_chars", 40000)))

    # 1. collect
    items: list[Item] = []
    for src in build_sources(cfg, state, only_sources):
        remaining = None if limit is None else limit - len(items)
        if remaining is not None and remaining <= 0:
            break
        try:
            for it in src.fetch(remaining):
                items.append(it)
                if limit is not None and len(items) >= limit:
                    break
        except Exception as exc:
            summary.error(src.name, "collect", exc)
    summary.collected = len(items)

    # 2. transcribe
    ready: list[Item] = []
    for it in items:
        if it.transcript:
            ready.append(it)
            continue
        if not it.media_path:
            summary.skipped += 1
            continue
        try:
            model = cfg["sources"].get(it.source, {}).get("whisper_model", "base")
            it.transcript, it.language = transcribe_media(it.media_path, model)
            if it.transcript:
                ready.append(it)
            else:
                summary.skipped += 1
        except Exception as exc:
            summary.skipped += 1
            log.info("skipping %s: cannot transcribe (%s)", Path(it.media_path).name, exc)

    # 3-4. classify + extract
    processed: list[Item] = []
    for it in ready:
        try:
            it.categories = classify(it)
            it.extraction, it.backend = extractor.extract(it)
            it.keywords = top_keywords(f"{it.title} {it.transcript}")
            summary.backends_used[it.backend] += 1
            processed.append(it)
        except Exception as exc:
            summary.error(it.id, "extract", exc)
    summary.llm_calls = extractor.llm_calls
    summary.breaker_open = extractor.breaker.is_open

    # 5. score (recurrence includes authors already recorded on tool notes)
    existing: dict[str, set[str]] = {}
    try:
        for _, meta in w.iter_notes(TOOLS):
            if meta.get("name"):
                existing[str(meta["name"])] = set(meta.get("authors") or [])
    except Exception as exc:
        summary.error("tools", "score", exc)
    rec = tool_recurrence(processed, existing)
    for it in processed:
        try:
            it.signal_score = signal_score(it, rec)
        except Exception as exc:
            summary.error(it.id, "score", exc)

    # 6. idea fit
    ideas_by_item: dict[str, list[dict[str, Any]]] = {}
    for it in processed:
        scored = []
        for idea in it.extraction.get("ideas", []):
            try:
                fit, verdict, reasons = score_idea(idea, profile)
                scored.append({**idea, "fit_score": fit, "verdict": verdict, "reasons": reasons})
            except Exception as exc:
                summary.error(it.id, "fit", exc)
        ideas_by_item[it.id] = scored

    # 7a. source notes (first pass; tool/idea links resolved in the link stage)
    written: list[Item] = []
    for it in processed:
        try:
            it.note_stem = resolve_source_stem(w, it)
            w.write(SOURCES, it.note_stem, source_meta(it),
                    render_source(it, w, ideas_by_item[it.id]))
            written.append(it)
            summary.notes["sources"] += 1
        except Exception as exc:
            summary.error(it.id, "write", exc)

    # 7b. tool notes (aggregated across the run, merged with existing notes)
    agg: dict[str, dict[str, Any]] = {}
    for it in written:
        for tool in it.extraction.get("tools", []):
            a = agg.setdefault(tool["name"], {"category": tool.get("category") or "other",
                                              "description": "", "url": None,
                                              "authors": set(), "mentions": []})
            a["description"] = a["description"] or tool.get("description") or ""
            a["url"] = a["url"] or tool.get("url")
            a["authors"].add(it.author or it.id)
            a["mentions"].append(it.note_stem)
    for name, a in sorted(agg.items()):
        try:
            stem = tool_stem(name)
            old, _ = w.read(TOOLS, stem)
            authors = sorted(set(old.get("authors") or []) | a["authors"])
            mentions = list(dict.fromkeys(list(old.get("mentions") or []) + a["mentions"]))
            meta = {
                "tags": ["tool", a["category"]],
                "type": "tool",
                "source": "nightshift",
                "score": min(100, 20 * len(authors)),
                "name": name,
                "category": old.get("category") or a["category"],
                "description": old.get("description") or a["description"],
                "url": old.get("url") or a["url"],
                "authors": authors,
                "mentions": mentions,
            }
            w.write(TOOLS, stem, meta, render_tool(name, meta, w))
            summary.notes["tools"] += 1
        except Exception as exc:
            summary.error(name, "write-tool", exc)

    # 7c. idea notes (an existing idea note with the same name is never overwritten)
    for it in written:
        for idea in ideas_by_item.get(it.id, []):
            try:
                stem = idea_stem(idea["title"])
                if w.exists(IDEAS, stem):
                    old, _ = w.read(IDEAS, stem)
                    if old.get("origin") != it.note_stem:
                        log.info("idea already captured: %s", stem)
                        continue
                meta = {
                    "tags": ["idea", *it.categories[:2]],
                    "type": "idea",
                    "source": it.source,
                    "score": idea["fit_score"],
                    "verdict": idea["verdict"],
                    "status": "new",
                    "origin": it.note_stem,
                    "summary": idea.get("idea", ""),
                }
                w.write(IDEAS, stem, meta, render_idea(idea, it.note_stem, w))
                summary.notes["ideas"] += 1
                summary.ideas.append((idea["fit_score"], idea["verdict"], stem))
            except Exception as exc:
                summary.error(it.id, "write-idea", exc)

    # 8. link: re-render source notes with related notes + tool/idea links
    try:
        corpus = [_note_ref(s, m) for s, m in w.iter_notes(SOURCES)]
    except Exception as exc:
        summary.error("sources", "link", exc)
        corpus = []
    max_links = int((cfg.get("linking") or {}).get("max_links", 6))
    for it in written:
        try:
            me = NoteRef(it.note_stem, set(it.categories), it.author, set(it.keywords))
            rel = related(me, corpus, max_links=max_links)
            w.write(SOURCES, it.note_stem, source_meta(it),
                    render_source(it, w, ideas_by_item[it.id], rel))
        except Exception as exc:
            summary.error(it.id, "link", exc)

    # 9. digest
    try:
        noise = int((cfg.get("scoring") or {}).get("noise_threshold", 35))
        d = build_digest(w, noise)
        if d:
            summary.digest = f"{cfg['folders'].get('digest', 'Digest')}/{d[0]}.md"
            summary.notes["digest"] += 1
    except Exception as exc:
        summary.error("digest", "digest", exc)

    # 10. state
    summary.processed = len(written)
    summary.top = sorted(((it.signal_score, it.note_stem) for it in written), reverse=True)
    summary.ideas.sort(reverse=True)
    if not dry_run:
        for it in written:
            state.mark_done(it.source, it.id)
        try:
            state.save()
        except Exception as exc:
            summary.error("state", "state", exc)
    summary.duration = time.monotonic() - t0
    return summary
