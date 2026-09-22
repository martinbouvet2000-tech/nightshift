"""Daily digest note: what came in today, ranked by signal and profile fit.

Rebuilt from the vault's notes created today, so re-running is idempotent.
"""

from __future__ import annotations

from typing import Any

from nightshift.notes import DIGEST, IDEAS, SOURCES, TOOLS
from nightshift.writer import VaultWriter


def build_digest(w: VaultWriter, noise_threshold: int = 35) -> tuple[str, dict[str, Any]] | None:
    today = w.today
    sources = [(s, m) for s, m in w.iter_notes(SOURCES) if str(m.get("created")) == today]
    if not sources:
        return None
    ideas = [(s, m) for s, m in w.iter_notes(IDEAS) if str(m.get("created")) == today]
    tools_today = sorted({s for s, m in w.iter_notes(TOOLS) if str(m.get("updated")) == today})

    sources.sort(key=lambda sm: (-int(sm[1].get("score") or 0), sm[0]))
    ideas.sort(key=lambda sm: (-int(sm[1].get("score") or 0), sm[0]))
    scores = [int(m.get("score") or 0) for _, m in sources]
    avg = round(sum(scores) / len(scores))
    noise = [(s, m) for s, m in sources if int(m.get("score") or 0) < noise_threshold]

    out = [f"{len(sources)} new item(s) · average signal **{avg}/100** · "
           f"{len(ideas)} new idea(s) · {len(tools_today)} tool note(s) touched"]

    top = [(s, m) for s, m in sources if int(m.get("score") or 0) >= noise_threshold][:10]
    if top:
        lines = [f"- **{m.get('score')}** · {w.link(SOURCES, s)}"
                 + (f" ({m.get('author')})" if m.get("author") else "") for s, m in top]
        out.append("## Top signal\n\n" + "\n".join(lines))
    if ideas:
        lines = [f"- **{m.get('score')}** · {w.link(IDEAS, s)} — {m.get('verdict', '')}"
                 for s, m in ideas[:10]]
        out.append("## Ideas by profile fit\n\n" + "\n".join(lines))
    if tools_today:
        out.append("## Tools mentioned\n\n" + ", ".join(w.link(TOOLS, s) for s in tools_today))
    if noise:
        lines = [f"- {m.get('score')} · {w.link(SOURCES, s)}" for s, m in noise[:10]]
        out.append(f"## Low signal (below {noise_threshold})\n\n" + "\n".join(lines))

    stem = f"Digest {today}"
    meta = {"tags": ["digest"], "type": "digest", "source": "nightshift", "score": avg,
            "items": len(sources), "ideas": len(ideas)}
    w.write(DIGEST, stem, meta, "\n\n".join(out))
    return stem, meta
