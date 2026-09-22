"""LLM backends and the circuit breaker.

Fallback chain (``backend: auto``):
    1. ``claude -p`` CLI, if the ``claude`` executable is on PATH
    2. Anthropic Messages API, if ``ANTHROPIC_API_KEY`` is set
    3. no LLM -> callers use the deterministic regex extractor

Keys are only ever read from the environment; nothing is logged or stored.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Protocol

log = logging.getLogger(__name__)

API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_API_MODEL = "claude-sonnet-5"


class LLMError(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    def complete(self, prompt: str) -> str:  # pragma: no cover - protocol
        ...


class ClaudeCLIBackend:
    name = "claude-cli"

    def __init__(self, executable: str, model: str = "sonnet", timeout: float = 300):
        self.executable = executable
        self.model = model
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        cmd = [self.executable, "-p"]
        if self.model:
            cmd += ["--model", self.model]
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude CLI timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise LLMError(f"claude CLI could not start: {exc}") from exc
        if r.returncode != 0 or not (r.stdout or "").strip():
            raise LLMError(f"claude CLI failed (exit {r.returncode}): {(r.stderr or '')[:200]}")
        return r.stdout


class AnthropicAPIBackend:
    """Tiny stdlib client for the Messages API (no SDK dependency)."""

    name = "anthropic-api"

    def __init__(self, api_key: str, model: str = DEFAULT_API_MODEL, max_tokens: int = 4000,
                 timeout: float = 300, base_url: str = "https://api.anthropic.com"):
        self._api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def complete(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages", data=body, method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMError(f"Anthropic API HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMError(f"Anthropic API request failed: {exc}") from exc
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise LLMError("Anthropic API returned no text")
        return text


class CircuitBreaker:
    """Stops LLM calls after ``threshold`` consecutive failures for the rest of the run."""

    def __init__(self, threshold: int = 5):
        self.threshold = max(1, int(threshold))
        self.consecutive_failures = 0
        self.is_open = False

    def allow(self) -> bool:
        return not self.is_open

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if not self.is_open and self.consecutive_failures >= self.threshold:
            self.is_open = True
            log.warning("LLM circuit breaker opened after %d consecutive failures; "
                        "using the regex extractor for the rest of this run",
                        self.consecutive_failures)


def select_backend(llm_cfg: dict[str, Any]) -> Backend | None:
    """Pick a backend according to ``llm.backend``. Returns None for regex-only."""
    mode = str(llm_cfg.get("backend", "auto")).lower()
    timeout = float(llm_cfg.get("timeout_seconds", 300))
    if mode == "regex":
        return None

    if mode in ("auto", "claude-cli"):
        exe = shutil.which("claude")
        if exe:
            return ClaudeCLIBackend(exe, llm_cfg.get("cli_model", "sonnet"), timeout)
        if mode == "claude-cli":
            log.warning("backend 'claude-cli' requested but `claude` is not on PATH; using regex")
            return None

    if mode in ("auto", "anthropic-api"):
        key = os.environ.get(API_KEY_ENV)
        base_url = llm_cfg.get("api_base_url", "https://api.anthropic.com")
        if key and not str(base_url).startswith("https://"):
            log.warning("llm.api_base_url must use https://; refusing to send the API key")
            key = None
        if key:
            return AnthropicAPIBackend(
                key,
                model=llm_cfg.get("api_model", DEFAULT_API_MODEL),
                max_tokens=int(llm_cfg.get("max_tokens", 4000)),
                timeout=timeout,
                base_url=base_url,
            )
        if mode == "anthropic-api":
            log.warning("backend 'anthropic-api' requested but %s is not set; using regex",
                        API_KEY_ENV)
            return None

    if mode not in ("auto", "claude-cli", "anthropic-api"):
        log.warning("unknown llm.backend %r; using regex", mode)
    return None
