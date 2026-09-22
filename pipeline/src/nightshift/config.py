"""Configuration loading: defaults <- config file (YAML or JSON) <- env vars."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "vault_path": None,
    "state_dir": None,  # default: <vault_path>/.nightshift
    "profile_path": None,
    "folders": {
        "sources": "Sources",
        "tools": "Tools",
        "ideas": "Ideas",
        "digest": "Digest",
    },
    "llm": {
        "backend": "auto",  # auto | claude-cli | anthropic-api | regex
        "api_model": "claude-sonnet-5",
        "cli_model": "sonnet",
        "api_base_url": "https://api.anthropic.com",
        "max_tokens": 4000,
        "timeout_seconds": 300,
        "max_transcript_chars": 40000,
        "circuit_breaker_threshold": 5,
    },
    "scoring": {"noise_threshold": 35},
    "linking": {"max_links": 6},
    "sources": {
        "youtube": {
            "enabled": False,
            "urls": [],
            "max_per_source": 15,
            "max_new_per_run": 12,
            "languages": ["en", "en-US", "en-GB"],
            "cookies_from_browser": None,
            "max_attempts": 3,
        },
        "local": {
            "enabled": True,
            "drop_folder": "./inbox",
            "recursive": False,
            "whisper_model": "base",
        },
    },
    "extra_tools": {},
}

CONFIG_CANDIDATES = ("nightshift.yaml", "nightshift.yml", "nightshift.json")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} must contain a mapping at top level")
    return data


def _resolve(p: Any, base: Path) -> str | None:
    if not p:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(str(p))))
    if not path.is_absolute():
        path = base / path
    return str(path.resolve())


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("NIGHTSHIFT_CONFIG")
    if env:
        return Path(env)
    for name in CONFIG_CANDIDATES:
        p = Path.cwd() / name
        if p.exists():
            return p
    return None


def load_config(path: str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load configuration. Relative paths are resolved against the config
    file's directory (or the current directory when no file is used)."""
    cfg_path = find_config(path)
    data: dict[str, Any] = {}
    base = Path.cwd()
    if cfg_path is not None:
        if not cfg_path.exists():
            raise FileNotFoundError(f"config file not found: {cfg_path}")
        data = _read_file(cfg_path)
        base = cfg_path.resolve().parent
    cfg = deep_merge(DEFAULTS, data)
    if overrides:
        cfg = deep_merge(cfg, overrides)

    env_vault = os.environ.get("NIGHTSHIFT_VAULT")
    if env_vault:
        cfg["vault_path"] = env_vault

    cfg["vault_path"] = _resolve(cfg.get("vault_path"), base)
    cfg["profile_path"] = _resolve(cfg.get("profile_path"), base)
    cfg["state_dir"] = _resolve(cfg.get("state_dir"), base) or (
        str(Path(cfg["vault_path"]) / ".nightshift") if cfg["vault_path"] else None
    )
    local = cfg["sources"]["local"]
    local["drop_folder"] = _resolve(local.get("drop_folder"), base)
    cfg["_config_file"] = str(cfg_path.resolve()) if cfg_path else None
    return cfg
