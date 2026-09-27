"""Replay a real `nightshift demo` run as a terminal.

This image sits under "Try it in one minute" and tells the reader what the
command will print. So it is not drawn from memory: this script *runs* the
demo in a throwaway directory, counts the notes it finds on disk, and draws
those counts. If the pipeline's output changes, re-running this script is the
only way the picture changes with it.

The run happens with cwd set to a temporary directory and no --out, so the
demo writes to its default ./demo-vault *inside* that directory — the same
path the README tells you to expect, and never a real vault. The directory is
deleted afterwards.

    python assets/build_demo.py

Counting, not transcribing: the note totals come from walking the vault the
run just produced. The printed summary is only used to cross-check them, and
the script refuses to draw anything if the two disagree.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "demo.svg"

# Same palette and grid as scripts/build_nightly.py on the profile repo: these
# two terminals are the same object seen twice, and must not drift apart.
T = {
    "bg": "#08090B", "chrome": "#14171C", "border": "#252A31",
    "text": "#F5F7FA", "dim": "#8B949E", "faint": "#4A515B",
    "accent": "#F0883E", "ok": "#3FB950", "blue": "#79C0FF",
    "mono": "ui-monospace,SFMono-Regular,'JetBrains Mono',Consolas,monospace",
}
W, LINE, TOP, PAD = 1200, 26, 92, 34
DOTS = (("#FF5F57", 26), ("#FEBC2E", 46), ("#28C840", 66))

# Folder in the produced vault -> the word the CLI summary uses for it.
KINDS = (("Sources", "sources"), ("Tools", "tools"),
         ("Ideas", "ideas"), ("Digest", "digest"))

VERDICT = {"worth exploring": "ok", "strong fit": "ok",
           "weak fit": "accent", "skip": "faint"}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run_demo(workdir):
    """Run the documented command and hand back (stdout, vault path)."""
    exe = Path(sys.executable).parent / "nightshift"
    cmd = [str(exe)] if exe.exists() or exe.with_suffix(".exe").exists() else \
        [sys.executable, "-m", "nightshift.cli"]
    p = subprocess.run(cmd + ["demo"], cwd=workdir, text=True,
                       capture_output=True)
    if p.returncode != 0:
        raise SystemExit(f"nightshift demo failed ({p.returncode}):\n{p.stderr}")
    return p.stdout, Path(workdir) / "demo-vault"


def counted(vault):
    """Count the notes the run actually wrote. This is the source of truth."""
    return {label: len(list((vault / folder).glob("*.md")))
            for folder, label in KINDS}


def parsed(stdout):
    """Pull the run's own numbers and score lines out of what it printed."""
    d = {"duration": "", "items": "", "backend": "", "digest": "",
         "summary": {}, "signal": [], "ideas": []}
    section = None
    for raw in stdout.splitlines():
        line = raw.rstrip()
        if m := re.match(r"nightshift run complete in (\S+)", line.strip()):
            d["duration"] = m.group(1)
        elif m := re.match(r"\s+backend:\s+(.*)", line):
            d["backend"] = m.group(1)
        elif m := re.match(r"\s+items:\s+(.*)", line):
            d["items"] = m.group(1)
        elif m := re.match(r"\s+notes:\s+(.*)", line):
            for n, word in re.findall(r"(\d+)\s+(\w+)", m.group(1)):
                d["summary"][word] = int(n)
        elif m := re.match(r"\s+digest:\s+(.*)", line):
            d["digest"] = m.group(1)
        elif re.match(r"\s+top signal:", line):
            section = "signal"
        elif re.match(r"\s+ideas by profile fit:", line):
            section = "ideas"
        elif section and re.match(r"\s+\d+\s", line):
            d[section].append(re.split(r"\s{2,}", line.strip()))
        elif not line.strip():
            section = None
    return d


def lines(c, d):
    """Every row is a counted value or a line the run printed. Nothing typed."""
    pad = lambda w: (w + ":").ljust(13)
    rows = [
        [(T["ok"], "you@laptop"), (T["dim"], ":~$ "), (T["text"], "nightshift demo")],
        [(T["ok"], "nightshift run complete"), (T["faint"], f' in {d["duration"]}')],
        [(T["blue"], f'  {pad("vault")}'), (T["text"], "./demo-vault")],
        [(T["blue"], f'  {pad("backend")}'), (T["dim"], d["backend"])],
        [(T["blue"], f'  {pad("items")}'), (T["dim"], d["items"])],
        [(T["blue"], f'  {pad("notes")}'),
         (T["accent"], str(c["sources"])), (T["dim"], " sources, "),
         (T["accent"], str(c["tools"])), (T["dim"], " tools, "),
         (T["accent"], str(c["ideas"])), (T["dim"], " ideas, "),
         (T["accent"], str(c["digest"])), (T["dim"], " digest")],
        [(T["blue"], "  top signal:")],
    ]
    for score, title in d["signal"]:
        rows.append([(T["accent"], score.rjust(7)), (T["text"], "  " + title)])
    rows.append([(T["blue"], "  ideas by profile fit:")])
    for score, verdict, title in d["ideas"]:
        rows.append([(T["accent"], score.rjust(7)),
                     (T[VERDICT.get(verdict, "dim")], "  " + verdict.ljust(16)),
                     (T["text"], title)])
    rows += [
        [(T["blue"], f'  {pad("digest")}'), (T["dim"], d["digest"])],
        [],
        [(T["faint"], "Open ./demo-vault in Obsidian, or check it against the "
                      "data contract with vault/audit.mjs --strict.")],
    ]
    return rows


def svg(c, d):
    rows = lines(c, d)
    h = TOP + len(rows) * LINE + 34
    total = c["sources"] + c["tools"] + c["ideas"] + c["digest"]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" '
         f'viewBox="0 0 {W} {h}" role="img" aria-labelledby="dt dd">',
         '<title id="dt">A real nightshift demo run</title>',
         f'<desc id="dd">Terminal replay of a real offline `nightshift demo` run: '
         f'{d["items"]}, written to demo-vault as {c["sources"]} source notes, '
         f'{c["tools"]} tool notes, {c["ideas"]} scored ideas and {c["digest"]} '
         f'digest — {total} notes in total, with no API key and no network.</desc>',
         "<style>"
         # Nothing here may start hidden. GitHub serves this file to the README
         # through an <img>, and Chrome freezes the SMIL clock at t=0 there: an
         # element that begins at opacity:0, or inside a clip path that begins
         # at width/height 0, stays invisible forever. The previous hand-written
         # version of this asset did exactly that and showed an empty terminal.
         # Only the cursor animates, because its base state is visible and a
         # frozen clock simply leaves it on.
         "@keyframes blink{50%{opacity:0}}.cur{animation:blink 1.05s step-end infinite}"
         "</style>",
         f'<rect width="{W}" height="{h}" rx="12" fill="{T["bg"]}" stroke="{T["border"]}"/>',
         f'<path d="M12 0h{W - 24}a12 12 0 0 1 12 12v40H0V12A12 12 0 0 1 12 0z" '
         f'fill="{T["chrome"]}"/>',
         f'<line x1="0" y1="52" x2="{W}" y2="52" stroke="{T["border"]}"/>']
    for col, cx in DOTS:
        o.append(f'<circle cx="{cx}" cy="26" r="6" fill="{col}"/>')
    o.append(f'<text x="{W / 2}" y="31" text-anchor="middle" font-family="{T["mono"]}" '
             f'font-size="12.5" fill="{T["dim"]}">nightshift demo '
             f'&#8212; offline, no API key, no network</text>')

    for i, row in enumerate(rows):
        if not row:
            continue
        y = TOP + i * LINE
        # one string, no newline between tspans: xml:space keeps every space literal
        spans = "".join(f'<tspan fill="{c_}">{esc(t)}</tspan>' for c_, t in row)
        o.append(f'<text x="{PAD}" y="{y}" '
                 f'font-family="{T["mono"]}" font-size="14.5" xml:space="preserve">'
                 f'{spans}</text>')

    y = TOP + len(rows) * LINE
    o.append(f'<text x="{PAD}" y="{y}" '
             f'font-family="{T["mono"]}" font-size="14.5">'
             f'<tspan fill="{T["ok"]}">you@laptop</tspan>'
             f'<tspan fill="{T["dim"]}">:~$ </tspan>'
             f'<tspan class="cur" fill="{T["accent"]}">&#9608;</tspan></text>')
    o.append("</svg>")
    return "\n".join(o)


def main():
    work = tempfile.mkdtemp(prefix="nightshift-demo-")
    try:
        stdout, vault = run_demo(work)
        c, d = counted(vault), parsed(stdout)
        # The picture must agree with the disk. If the CLI summary and the files
        # it wrote disagree, one of them is lying and neither gets published.
        if d["summary"] and d["summary"] != c:
            raise SystemExit(f"counted {c} on disk but the run printed "
                             f"{d['summary']} — refusing to draw either")
        OUT.write_text(svg(c, d), encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size} bytes  "
          f"counted {c} in {d['duration']}")


if __name__ == "__main__":
    main()
