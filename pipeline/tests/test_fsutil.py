from __future__ import annotations

import os

import pytest

from nightshift import fsutil
from nightshift.fsutil import atomic_write_text, safe_join, sanitize_filename


@pytest.mark.parametrize("raw", [
    "../../etc/passwd",
    "..\\..\\Windows\\System32",
    "a/../../b",
    "....",
    "/absolute/path",
    "C:\\temp\\x",
])
def test_sanitize_removes_traversal(raw):
    s = sanitize_filename(raw)
    assert "/" not in s and "\\" not in s
    assert ".." not in s
    assert ":" not in s
    assert s and not s.startswith(".")


@pytest.mark.parametrize("raw", ["CON", "con", "NUL.txt", "com1", "LPT9", "aux.md"])
def test_sanitize_reserved_windows_names(raw):
    s = sanitize_filename(raw)
    assert s.startswith("_")


def test_sanitize_strips_illegal_and_link_breaking_chars():
    s = sanitize_filename('What? A "great" <tool> | [[link]] #tag ^block *now*')
    for ch in '?"<>|[]#^*':
        assert ch not in s
    assert s == "What A great tool link tag block now"


def test_sanitize_empty_and_long():
    assert sanitize_filename("") == "untitled"
    assert sanitize_filename(None) == "untitled"
    assert sanitize_filename(" . . ") == "untitled"
    long = sanitize_filename("x" * 500, max_len=50)
    assert len(long) == 50


def test_sanitize_keeps_unicode():
    assert sanitize_filename("Café à la carte") == "Café à la carte"


def test_safe_join_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        safe_join(tmp_path, "..", "outside.md")
    with pytest.raises(ValueError):
        safe_join(tmp_path, "sub", "..", "..", "outside.md")
    assert safe_join(tmp_path, "sub", "ok.md") == (tmp_path / "sub" / "ok.md").resolve()


def test_atomic_write_creates_and_replaces(tmp_path):
    target = tmp_path / "deep" / "note.md"
    atomic_write_text(target, "one")
    assert target.read_text(encoding="utf-8") == "one"
    atomic_write_text(target, "two\nlines")
    assert target.read_text(encoding="utf-8") == "two\nlines"
    leftovers = [p for p in target.parent.iterdir() if p.name != "note.md"]
    assert leftovers == []


def test_atomic_write_failure_keeps_original(tmp_path, monkeypatch):
    target = tmp_path / "note.md"
    atomic_write_text(target, "original")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(fsutil.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new content")
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


def test_json_state_roundtrip_and_corruption(tmp_path):
    p = tmp_path / "state.json"
    fsutil.save_json(p, {"a": {"x": "done"}})
    assert fsutil.load_json(p, {}) == {"a": {"x": "done"}}
    p.write_text("{not json", encoding="utf-8")
    assert fsutil.load_json(p, {"fresh": True}) == {"fresh": True}
    assert not os.path.exists(tmp_path / "missing.json")
    assert fsutil.load_json(tmp_path / "missing.json", []) == []
