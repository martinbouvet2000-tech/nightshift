"""Minimal, deterministic YAML frontmatter rendering and parsing.

Rendering is done by hand so the output is stable and always follows the
note contract (block-style lists, unquoted ISO dates). Parsing uses PyYAML.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import yaml

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_TAG_RE = re.compile(r"[^a-z0-9/_-]+")
# Strings safe to emit unquoted (lower-case identifiers such as tags and types).
_PLAIN_RE = re.compile(r"^[a-z][a-z0-9/_-]*$")
_YAML_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "y", "n", "nan", "inf"}


def normalize_tag(tag: Any) -> str | None:
    t = str(tag or "").strip().lstrip("#").lower().replace(" ", "-")
    t = _TAG_RE.sub("", t).strip("-/")
    return t or None


def normalize_tags(tags: list[Any]) -> list[str]:
    out: list[str] = []
    for t in tags:
        n = normalize_tag(t)
        if n and n not in out:
            out.append(n)
    return out


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else v.isoformat()
    s = str(v)
    if _DATE_RE.match(s):
        return s
    if _PLAIN_RE.match(s) and s not in _YAML_RESERVED:
        return s
    # A JSON string literal is a valid YAML double-quoted scalar.
    return json.dumps(s, ensure_ascii=False)


def dump(meta: dict[str, Any]) -> str:
    """Render ``meta`` as a frontmatter block (including the ``---`` fences)."""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            if not items:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_scalar(x)}" for x in items)
        elif isinstance(value, dict):
            if not value:
                lines.append(f"{key}: {{}}")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  {k}: {_scalar(v)}" for k, v in value.items())
        else:
            lines.append(f"{key}: {_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _stringify_dates(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()[:10]
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    return obj


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split a note into (frontmatter dict, body). Never raises."""
    m = _FM_RE.match(text or "")
    if not m:
        return {}, text or ""
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}
    return _stringify_dates(meta), text[m.end():]
