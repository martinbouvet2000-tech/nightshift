from __future__ import annotations

from datetime import date

import pytest
import yaml

from nightshift import frontmatter
from nightshift.writer import VaultWriter, neutralize_links

from conftest import assert_note_contract

FOLDERS = {"sources": "Sources", "tools": "Tools", "ideas": "Ideas", "digest": "Digest"}


def test_dump_parse_roundtrip():
    meta = {"tags": ["tool", "ai/llm"], "created": "2026-01-02", "score": 42, "flag": True,
            "title": 'Quotes " and: colons', "empty": [], "none": None, "word": "null"}
    text = frontmatter.dump(meta) + "\nbody"
    parsed, body = frontmatter.parse(text)
    assert parsed == meta
    assert body.strip() == "body"
    assert "tags:\n  - tool\n  - ai/llm" in text
    assert "created: 2026-01-02" in text


def test_parse_garbage_never_raises():
    assert frontmatter.parse("no frontmatter") == ({}, "no frontmatter")
    meta, _ = frontmatter.parse("---\n: : [\n---\nbody")
    assert meta == {}


def test_normalize_tags():
    assert frontmatter.normalize_tags(["#AI Tools", "ai-tools", "", None, "C++"]) == ["ai-tools", "c"]


def test_writer_enforces_contract(tmp_path):
    w = VaultWriter(tmp_path, FOLDERS, today=date(2026, 3, 1))
    p = w.write("tools", "My Tool", {"tags": ["Tool", "#LLM"], "type": "tool", "score": 7}, "Body")
    meta = assert_note_contract(p)
    assert meta["tags"] == ["tool", "llm"]
    assert meta["created"] == "2026-03-01" and meta["updated"] == "2026-03-01"
    yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])  # valid YAML


def test_writer_preserves_created_on_update(tmp_path):
    w1 = VaultWriter(tmp_path, FOLDERS, today=date(2026, 1, 1))
    w1.write("tools", "T", {"tags": ["tool"], "score": 1}, "v1")
    w2 = VaultWriter(tmp_path, FOLDERS, today=date(2026, 2, 1))
    p = w2.write("tools", "T", {"tags": ["tool"], "score": 2}, "v2")
    meta = assert_note_contract(p)
    assert meta["created"] == "2026-01-01" and meta["updated"] == "2026-02-01"


def test_writer_rejects_unsafe_names(tmp_path):
    w = VaultWriter(tmp_path, FOLDERS)
    for bad in ("../escape", "a/b", "CON", ""):
        with pytest.raises(ValueError):
            w.write("sources", bad, {"tags": ["x"]}, "body")
    assert not (tmp_path.parent / "escape.md").exists()


def test_writer_folder_config_cannot_escape_vault(tmp_path):
    vault = tmp_path / "vault"
    w = VaultWriter(vault, {"sources": "../../outside"})
    p = w.write("sources", "Note", {"tags": ["x"]}, "body")
    assert vault.resolve() in p.parents


def test_link_only_to_existing_notes(tmp_path):
    w = VaultWriter(tmp_path, FOLDERS)
    assert w.link("tools", "Ghost") == "Ghost"
    w.write("tools", "Real", {"tags": ["tool"]}, "x")
    assert w.link("tools", "Real") == "[[Real]]"


def test_dry_run_writes_nothing_but_tracks_links(tmp_path):
    w = VaultWriter(tmp_path, FOLDERS, dry_run=True)
    w.write("tools", "Planned", {"tags": ["tool"]}, "x")
    assert not any(tmp_path.rglob("*.md"))
    assert w.link("tools", "Planned") == "[[Planned]]"


def test_neutralize_links():
    assert "[[" not in neutralize_links("see [[Secret note]] now")
    assert neutralize_links("# not a heading").startswith("\\#")
