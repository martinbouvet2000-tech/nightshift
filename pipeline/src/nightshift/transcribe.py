"""Transcription helpers: subtitle parsing (VTT/SRT) and optional Whisper."""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from typing import Any

log = logging.getLogger(__name__)

_TIMESTAMP = re.compile(r"-->")
_CUE_NUMBER = re.compile(r"^\d+$")
_TAGS = re.compile(r"<[^>]+>")
_WHISPER_MODELS: dict[str, Any] = {}


def parse_subtitles(text: str) -> str:
    """Convert WebVTT or SRT content into plain transcript text.

    Drops headers, cue numbers, timestamps, NOTE/STYLE blocks and inline tags,
    and removes the consecutive duplicate lines typical of auto-captions.
    """
    lines: list[str] = []
    skip_block = False
    for raw in (text or "").lstrip("﻿").splitlines():
        line = raw.strip()
        if not line:
            skip_block = False
            continue
        if skip_block:
            continue
        if line.startswith("WEBVTT") or line.startswith(("Kind:", "Language:")):
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if _TIMESTAMP.search(line) or _CUE_NUMBER.match(line):
            continue
        clean = _TAGS.sub("", line).strip()
        clean = re.sub(r"&nbsp;", " ", clean)
        if clean and (not lines or lines[-1] != clean):
            lines.append(clean)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def transcribe_media(path: str, model_name: str = "base") -> tuple[str, str]:
    """Transcribe an audio/video file with Whisper. Returns (text, language).

    Raises RuntimeError when Whisper or ffmpeg is unavailable.
    """
    if not whisper_available():
        raise RuntimeError("Whisper is not installed (pip install 'nightshift[whisper]')")
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not on PATH (required by Whisper)")
    import whisper  # type: ignore[import-not-found]

    model = _WHISPER_MODELS.get(model_name)
    if model is None:
        log.info("loading Whisper model '%s' (first use can take a while)", model_name)
        model = whisper.load_model(model_name)
        _WHISPER_MODELS[model_name] = model
    result = model.transcribe(path)
    return str(result.get("text", "")).strip(), str(result.get("language", ""))
