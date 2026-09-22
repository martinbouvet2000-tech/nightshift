from __future__ import annotations

import time
from datetime import date

from nightshift import frontmatter
from nightshift.cli import main
from nightshift.config import DEFAULTS, deep_merge, load_config
from nightshift.pipeline import run_pipeline

from conftest import assert_links_resolve, assert_note_contract


def test_demo_end_to_end(tmp_path, capsys):
    out = tmp_path / "vault"
    t0 = time.monotonic()
    code = main(["demo", "--out", str(out)])
    elapsed = time.monotonic() - t0
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert elapsed < 60
    assert "4 collected, 4 processed" in printed and "0 error(s)" in printed

    sources = list((out / "Sources").glob("*.md"))
    assert len(sources) == 4
    assert len(list((out / "Tools").glob("*.md"))) >= 10
    assert len(list((out / "Ideas").glob("*.md"))) >= 3
    digests = list((out / "Digest").glob("*.md"))
    assert len(digests) == 1

    for note in out.rglob("*.md"):
        assert_note_contract(note)
    assert_links_resolve(out)

    types = {frontmatter.parse(p.read_text(encoding="utf-8"))[0]["type"] for p in out.rglob("*.md")}
    assert types == {"source", "tool", "idea", "digest"}
    # related-notes linking happened
    assert any("## Related" in p.read_text(encoding="utf-8") for p in sources)
    # engagement bait ranks lowest
    scores = {frontmatter.parse(p.read_text(encoding="utf-8"))[0]["title"]:
              frontmatter.parse(p.read_text(encoding="utf-8"))[0]["score"] for p in sources}
    assert min(scores, key=scores.get).startswith("I Replaced My Whole Agency")


def _cfg(tmp_path, examples_dir, **extra):
    return deep_merge(DEFAULTS, {
        "vault_path": str(tmp_path / "vault"),
        "state_dir": str(tmp_path / "state"),
        "llm": {"backend": "regex"},
        "sources": {"local": {"enabled": True, "drop_folder": str(examples_dir)}},
        **extra,
    })


def test_second_run_skips_processed_items(tmp_path, examples_dir):
    cfg = _cfg(tmp_path, examples_dir)
    first = run_pipeline(cfg, today=date(2026, 5, 1))
    assert first.processed == 4
    second = run_pipeline(cfg, today=date(2026, 5, 2))
    assert second.collected == 0 and second.processed == 0 and second.digest is None


def test_dry_run_writes_nothing(tmp_path, examples_dir):
    cfg = _cfg(tmp_path, examples_dir)
    s = run_pipeline(cfg, dry_run=True)
    assert s.processed == 4 and s.notes["sources"] == 4
    assert not (tmp_path / "vault").exists() or not any((tmp_path / "vault").rglob("*.md"))
    assert not (tmp_path / "state" / "state.json").exists()


def test_limit(tmp_path, examples_dir):
    s = run_pipeline(_cfg(tmp_path, examples_dir), limit=2)
    assert s.collected == 2 and s.processed == 2


def test_one_bad_item_does_not_abort(tmp_path, examples_dir, monkeypatch):
    import nightshift.pipeline as pl

    real = pl.classify

    def flaky(item, *a, **k):
        if item.title.startswith("Five Prompting"):
            raise RuntimeError("synthetic failure")
        return real(item, *a, **k)

    monkeypatch.setattr(pl, "classify", flaky)
    s = run_pipeline(_cfg(tmp_path, examples_dir))
    assert s.processed == 3
    assert len(s.errors) == 1 and s.errors[0][1] == "extract"
    for note in (tmp_path / "vault").rglob("*.md"):
        assert_note_contract(note)
    assert_links_resolve(tmp_path / "vault")


def test_media_without_whisper_is_skipped(tmp_path, monkeypatch):
    import nightshift.pipeline as pl

    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "talk.mp3").write_bytes(b"\x00" * 16)

    def no_whisper(path, model):
        raise RuntimeError("Whisper is not installed")

    monkeypatch.setattr(pl, "transcribe_media", no_whisper)
    s = run_pipeline(_cfg(tmp_path, drop))
    assert s.collected == 1 and s.skipped == 1 and s.processed == 0 and not s.errors


def test_config_env_and_relative_paths(tmp_path, monkeypatch):
    cfg_file = tmp_path / "nightshift.yaml"
    cfg_file.write_text("vault_path: ./my-vault\nsources:\n  local:\n    drop_folder: ./in\n",
                        encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg["vault_path"] == str((tmp_path / "my-vault").resolve())
    assert cfg["sources"]["local"]["drop_folder"] == str((tmp_path / "in").resolve())
    assert cfg["state_dir"].endswith(".nightshift")
    monkeypatch.setenv("NIGHTSHIFT_VAULT", str(tmp_path / "env-vault"))
    assert load_config(str(cfg_file))["vault_path"] == str((tmp_path / "env-vault").resolve())


def test_health_command(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NIGHTSHIFT_VAULT", str(tmp_path / "v"))
    monkeypatch.chdir(tmp_path)
    code = main(["health"])
    out = capsys.readouterr().out
    assert "llm backend" in out and "vault" in out
    assert code == 0


def test_run_without_vault_fails_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--dry-run"]) == 2
    assert "no vault configured" in capsys.readouterr().err


def test_example_config_is_valid(monkeypatch):
    from conftest import PIPELINE_DIR

    cfg = load_config(str(PIPELINE_DIR / "config.example.yaml"))
    assert cfg["llm"]["api_model"] == "claude-sonnet-5"
    assert cfg["llm"]["circuit_breaker_threshold"] == 5
    assert cfg["sources"]["youtube"]["enabled"] is False
    assert set(cfg["folders"]) == {"sources", "tools", "ideas", "digest"}
