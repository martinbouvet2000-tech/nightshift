from __future__ import annotations

import re
from pathlib import Path

import pytest

from nightshift import frontmatter

PIPELINE_DIR = Path(__file__).resolve().parents[1]
EXAMPLES = PIPELINE_DIR / "examples"
PROFILE = PIPELINE_DIR / "profile.example.yaml"


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch):
    """Tests never touch a real LLM: hide the API key and the claude CLI."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NIGHTSHIFT_VAULT", raising=False)
    monkeypatch.delenv("NIGHTSHIFT_CONFIG", raising=False)
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(shutil, "which",
                        lambda name, *a, **k: None if name == "claude" else real_which(name, *a, **k))


WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def assert_note_contract(path: Path) -> dict:
    """Assert the vault data contract for a single note; return its frontmatter."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: missing frontmatter"
    meta, body = frontmatter.parse(text)
    for key in ("tags", "created", "updated", "type", "source", "score"):
        assert key in meta, f"{path.name}: missing '{key}'"
    assert isinstance(meta["tags"], list) and meta["tags"], f"{path.name}: tags must be a non-empty list"
    assert re.search(r"^tags:\n  - ", text, re.M), f"{path.name}: tags must be a block-style YAML list"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta["created"]))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta["updated"]))
    assert isinstance(meta["score"], int) and 0 <= meta["score"] <= 100
    first_heading = next(line for line in body.splitlines() if line.strip())
    assert first_heading == f"# {path.stem}", f"{path.name}: H1 must equal the file name"
    return meta


def all_stems(vault: Path) -> set[str]:
    return {p.stem for p in vault.rglob("*.md")}


def assert_links_resolve(vault: Path) -> None:
    stems = all_stems(vault)
    for p in vault.rglob("*.md"):
        for target in WIKILINK.findall(p.read_text(encoding="utf-8")):
            assert target.strip() in stems, f"{p.name}: dangling wikilink [[{target}]]"
