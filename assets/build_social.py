"""Build the repository's social preview card (1280x640).

This is the image Reddit, X, Slack and LinkedIn show when someone shares the
repo, so it carries the one-line pitch and the facts a reader can check, not
decoration. GitHub has no API for the social preview: the PNG is uploaded once
in Settings > General > Social preview.

    python assets/build_social.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "social-preview.svg"
W, H = 1280, 640
T = {
    "bg": "#0B0D10", "border": "#252A31", "text": "#F5F7FA", "muted": "#8B949E",
    "faint": "#4A515B", "accent": "#F0883E", "ok": "#3FB950",
    "sans": "-apple-system,'Segoe UI',Inter,Helvetica,Arial,sans-serif",
    "mono": "ui-monospace,SFMono-Regular,Consolas,monospace",
}
FACTS = [("89", "tests"), ("2", "operating systems in CI"), ("0", "API keys to try it")]


def clock():
    """The 24-hour arc: the hours the agent works, the hand parked at 00:30."""
    import math
    p = ['<g transform="translate(1075,320)">']
    p.append(f'<path d="M0 -120 A120 120 0 0 1 85 85" fill="none" stroke="{T["text"]}" '
             f'stroke-opacity=".05" stroke-width="38"/>')
    p.append(f'<circle r="120" fill="none" stroke="{T["border"]}"/>')
    for hour, label in ((0, "00"), (6, "06"), (12, "12"), (18, "18")):
        a = (hour / 24) * 2 * math.pi - math.pi / 2
        p.append(f'<line x1="{120 * math.cos(a):.1f}" y1="{120 * math.sin(a):.1f}" '
                 f'x2="{132 * math.cos(a):.1f}" y2="{132 * math.sin(a):.1f}" stroke="{T["muted"]}"/>')
        p.append(f'<text x="{152 * math.cos(a):.1f}" y="{152 * math.sin(a) + 5:.1f}" '
                 f'text-anchor="middle" font-family="{T["mono"]}" font-size="14" '
                 f'fill="{T["muted"]}">{label}</text>')
    for x, y in ((-8, -100), (74, -71), (100, 11), (-100, 9)):
        p.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{T["accent"]}"/>')
    p.append(f'<line x1="0" y1="0" x2="-60" y2="-60" stroke="{T["text"]}" stroke-width="3" '
             f'stroke-linecap="round"/>')
    p.append(f'<circle r="5" fill="{T["text"]}"/>')
    p.append(f'<text y="205" text-anchor="middle" font-family="{T["mono"]}" font-size="13" '
             f'fill="{T["faint"]}" letter-spacing="2">00:30 · EVERY DAY</text>')
    p.append("</g>")
    return "".join(p)


def main():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<defs><pattern id="g" width="40" height="40" patternUnits="userSpaceOnUse">'
         f'<path d="M40 0H0V40" fill="none" stroke="{T["border"]}" stroke-opacity=".5"/></pattern></defs>',
         f'<rect width="{W}" height="{H}" fill="{T["bg"]}"/>',
         f'<rect width="{W}" height="{H}" fill="url(#g)"/>',
         f'<rect x="0" y="0" width="{W}" height="6" fill="{T["accent"]}"/>',
         f'<text x="80" y="150" font-family="{T["mono"]}" font-size="15" fill="{T["accent"]}" '
         f'letter-spacing="3.5">OPEN SOURCE · PYTHON + NODE</text>',
         f'<text x="76" y="250" font-family="{T["sans"]}" font-size="82" font-weight="700" '
         f'fill="{T["text"]}" letter-spacing="-2">nightshift</text>',
         f'<text x="80" y="308" font-family="{T["sans"]}" font-size="31" fill="{T["muted"]}">'
         f'A second brain that works while you sleep.</text>',
         f'<line x1="80" y1="358" x2="860" y2="358" stroke="{T["border"]}"/>']
    for i, (n, label) in enumerate(FACTS):
        x = 80 + i * 200
        o.append(f'<text x="{x}" y="422" font-family="{T["sans"]}" font-size="42" '
                 f'font-weight="700" fill="{T["text"]}">{n}</text>')
        o.append(f'<text x="{x}" y="450" font-family="{T["mono"]}" font-size="13" '
                 f'fill="{T["muted"]}">{label}</text>')
    o.append(f'<text x="80" y="536" font-family="{T["mono"]}" font-size="16" fill="{T["faint"]}">'
             f'$ <tspan fill="{T["text"]}">nightshift demo</tspan>'
             f'<tspan fill="{T["faint"]}">   # offline, no key, under a minute</tspan></text>')
    o.append(f'<text x="80" y="578" font-family="{T["mono"]}" font-size="14" fill="{T["muted"]}">'
             f'github.com/martinbouvet2000-tech/nightshift</text>')
    o.append(clock())
    o.append("</svg>")
    OUT.write_text("\n".join(o), encoding="utf-8")
    print(f"{OUT.name}  {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
