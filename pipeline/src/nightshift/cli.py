"""Command-line interface: ``nightshift run | demo | health``."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from nightshift import __version__

log = logging.getLogger("nightshift")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def examples_dir() -> Path | None:
    """Locate the bundled sample transcripts (``pipeline/examples``)."""
    candidates = [
        Path(__file__).resolve().parents[2] / "examples",  # editable / source checkout
        Path.cwd() / "examples",
        Path.cwd() / "pipeline" / "examples",
    ]
    for c in candidates:
        if c.is_dir() and any(c.glob("*.md")):
            return c
    return None


def cmd_run(args: argparse.Namespace) -> int:
    from nightshift.config import load_config
    from nightshift.pipeline import run_pipeline

    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    only = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None
    try:
        summary = run_pipeline(cfg, only_sources=only, dry_run=args.dry_run, limit=args.limit,
                               backend_override=args.backend)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(summary.format())
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from nightshift.config import DEFAULTS, deep_merge
    from nightshift.pipeline import run_pipeline

    ex = Path(args.examples) if args.examples else examples_dir()
    if not ex or not ex.is_dir():
        print("error: sample transcripts not found; pass --examples PATH", file=sys.stderr)
        return 2
    out = Path(args.out).resolve()
    profile = ex / "profile.example.yaml"
    if not profile.exists():
        profile = ex.parent / "profile.example.yaml"
    with tempfile.TemporaryDirectory(prefix="nightshift-demo-state-") as state_dir:
        cfg = deep_merge(DEFAULTS, {
            "vault_path": str(out),
            "state_dir": state_dir,  # fresh state: the demo always processes every sample
            "profile_path": str(profile) if profile.exists() else None,
            "llm": {"backend": "regex"},  # offline, no key, deterministic
            "sources": {"youtube": {"enabled": False},
                        "local": {"enabled": True, "drop_folder": str(ex)}},
        })
        summary = run_pipeline(cfg, only_sources=["local"])
    print(summary.format())
    print(f"\nOpen {out} in Obsidian (or any Markdown editor) to browse the result.")
    return 0 if not summary.errors else 1


def cmd_health(args: argparse.Namespace) -> int:
    from nightshift.config import load_config
    from nightshift.health import FAIL, format_checks, run_checks

    cfg, err = None, None
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        err = str(exc)
    checks = run_checks(cfg, err)
    print(f"nightshift {__version__} health check")
    print(format_checks(checks))
    return 1 if any(status == FAIL for _, status, _ in checks) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nightshift", description=__doc__)
    p.add_argument("--version", action="version", version=f"nightshift {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging on stderr")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the pipeline on the configured sources")
    r.add_argument("--config", help="config file (YAML/JSON); default: $NIGHTSHIFT_CONFIG or ./nightshift.yaml")
    r.add_argument("--sources", help="comma-separated subset, e.g. youtube,local")
    r.add_argument("--dry-run", action="store_true", help="process everything but write nothing")
    r.add_argument("--limit", type=int, help="maximum number of new items")
    r.add_argument("--backend", choices=["auto", "claude-cli", "anthropic-api", "regex"],
                   help="override llm.backend")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("demo", help="offline demo on bundled sample transcripts")
    d.add_argument("--out", default="demo-vault", help="output vault folder (default: ./demo-vault)")
    d.add_argument("--examples", help="folder of sample transcripts (default: bundled examples)")
    d.set_defaults(func=cmd_demo)

    h = sub.add_parser("health", help="check the environment and configuration")
    h.add_argument("--config", help="config file (YAML/JSON)")
    h.set_defaults(func=cmd_health)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
