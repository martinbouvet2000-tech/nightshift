"""Environment health check (``nightshift health``)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from nightshift.llm import API_KEY_ENV
from nightshift.sources.youtube import ytdlp_available
from nightshift.transcribe import ffmpeg_available, whisper_available

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".nightshift-health-", delete=True):
            pass
        return True
    except OSError:
        return False


def run_checks(cfg: dict[str, Any] | None, cfg_error: str | None = None) -> list[tuple[str, str, str]]:
    checks: list[tuple[str, str, str]] = []
    py = sys.version_info
    checks.append(("python", OK if py >= (3, 10) else FAIL, f"{py.major}.{py.minor}.{py.micro}"))

    if cfg_error:
        checks.append(("config", FAIL, cfg_error))
        return checks
    cfg = cfg or {}
    checks.append(("config", OK, cfg.get("_config_file") or "defaults (no config file found)"))

    vault = cfg.get("vault_path")
    if not vault:
        checks.append(("vault", FAIL, "not set (NIGHTSHIFT_VAULT or vault_path)"))
    else:
        checks.append(("vault", OK if _writable(Path(vault)) else FAIL, vault))

    profile = cfg.get("profile_path")
    if not profile:
        checks.append(("profile", WARN, "not set: ideas are scored without personal fit"))
    else:
        checks.append(("profile", OK if Path(profile).exists() else WARN, profile))

    srcs = cfg.get("sources") or {}
    local = srcs.get("local") or {}
    if local.get("enabled"):
        folder = local.get("drop_folder")
        checks.append(("local drop folder", OK if folder and Path(folder).is_dir() else WARN,
                       folder or "not set"))
    yt = srcs.get("youtube") or {}
    if yt.get("enabled"):
        checks.append(("yt-dlp", OK if ytdlp_available() else FAIL,
                       "installed" if ytdlp_available() else "missing: pip install 'nightshift[youtube]'"))
        checks.append(("youtube urls", OK if yt.get("urls") else WARN, f"{len(yt.get('urls') or [])} configured"))
    else:
        checks.append(("yt-dlp", OK if ytdlp_available() else WARN,
                       "installed" if ytdlp_available() else "not installed (youtube source disabled)"))

    checks.append(("whisper", OK if whisper_available() else WARN,
                   "installed" if whisper_available() else "not installed: audio/video files will be skipped"))
    checks.append(("ffmpeg", OK if ffmpeg_available() else WARN,
                   "on PATH" if ffmpeg_available() else "not on PATH (needed by Whisper)"))

    backend = str((cfg.get("llm") or {}).get("backend", "auto"))
    cli = shutil.which("claude") is not None
    key = bool(os.environ.get(API_KEY_ENV))
    if backend == "regex":
        detail = "regex only (configured)"
    elif cli and backend in ("auto", "claude-cli"):
        detail = "claude CLI"
    elif key and backend in ("auto", "anthropic-api"):
        detail = f"Anthropic API ({API_KEY_ENV} is set)"
    else:
        detail = "regex fallback (no claude CLI on PATH, no API key in env)"
    checks.append(("llm backend", OK if "fallback" not in detail else WARN, detail))

    state_dir = cfg.get("state_dir")
    if state_dir:
        checks.append(("state dir", OK if _writable(Path(state_dir)) else FAIL, state_dir))
    return checks


def format_checks(checks: list[tuple[str, str, str]]) -> str:
    width = max(len(n) for n, _, _ in checks)
    return "\n".join(f"  [{status:>4}] {name:<{width}}  {detail}" for name, status, detail in checks)
