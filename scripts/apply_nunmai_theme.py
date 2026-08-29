#!/usr/bin/env python3
"""Apply Nunmai visual identity to the terminal UI (CLI + TUI).

Run after scripts/rebrand_to_nunmai.py. Idempotent.

- Block-letter logo: "NUNMAI ENGINE" (ANSI Shadow font) replaces the Nunmai art.
- Hero mark: the Nunmai logo (nunmai.in/favicon.svg) replaces the caduceus.
- Symbol: ⚕ (caduceus) -> ✦ everywhere.
- Palette: Nunmai gold -> Nunmai mint / deep green (brand colours from nunmai.in).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "build", ".next"}

# --- Brand palette (nunmai.in) -------------------------------------------
MINT = "#6BE7C8"       # primary
TEAL = "#3FCFA9"       # accent
GREEN = "#0B6B4F"      # border / deep
DIM = "#2E9C7C"        # dim mint
GOLD = "#D6B36C"       # brand gold accent (labels)
CREAM = "#EFE9D7"      # text
SURFACE = "#052819"    # panels / status bar
ACTIVE = "#1F4A3D"
SELECT = "#1B3A32"
STATUS_DIM = "#5B8A7C"

COLOR_MAP = {
    "#FFD700": MINT,
    "#FFBF00": TEAL,
    "#CD7F32": GREEN,
    "#B8860B": DIM,
    "#DAA520": GOLD,
    "#FFF8DC": CREAM,
    "#1A1A2E": SURFACE,
    "#333355": ACTIVE,
    "#3A3A55": SELECT,
    "#8A7A4A": STATUS_DIM,
}
COLOR_RE = re.compile("|".join(re.escape(k) for k in COLOR_MAP), re.IGNORECASE)

# Where palette substitution applies (UI source + its tests only; never skills/docs)
PALETTE_SCOPE = (
    "cli.py",
    "nunmai_cli/",
    "ui-tui/src/",
    "tui_gateway/",
    "web/src/themes/",
    "tests/cli/",
    "tests/nunmai_cli/",
)

LOGO_LINES = [
    "███╗   ██╗██╗   ██╗███╗   ██╗███╗   ███╗ █████╗ ██╗    ███████╗███╗   ██╗ ██████╗ ██╗███╗   ██╗███████╗",
    "████╗  ██║██║   ██║████╗  ██║████╗ ████║██╔══██╗██║    ██╔════╝████╗  ██║██╔════╝ ██║████╗  ██║██╔════╝",
    "██╔██╗ ██║██║   ██║██╔██╗ ██║██╔████╔██║███████║██║    █████╗  ██╔██╗ ██║██║  ███╗██║██╔██╗ ██║█████╗  ",
    "██║╚██╗██║██║   ██║██║╚██╗██║██║╚██╔╝██║██╔══██║██║    ██╔══╝  ██║╚██╗██║██║   ██║██║██║╚██╗██║██╔══╝  ",
    "██║ ╚████║╚██████╔╝██║ ╚████║██║ ╚═╝ ██║██║  ██║██║    ███████╗██║ ╚████║╚██████╔╝██║██║ ╚████║███████╗",
    "╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝    ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝╚══════╝",
]
LOGO_GRADIENT = ["bold " + MINT, "bold " + MINT, TEAL, TEAL, GREEN, GREEN]

# Nunmai mark: rasterised from https://nunmai.in/favicon.svg (32px, half-block cells).
LOGO_FG = "#EFE9D7"   # cream mark
LOGO_BG = "#052819"   # deep green badge
HERO_LINES = [
    "         ▄▄██████████▄▄         ",
    "       ▄████████████████▄       ",
    "     ▄███████▀▀▀▀▀▀███████▄     ",
    "    ▄██████▀        ▀██████▄    ",
    "    ██████            ██████    ",
    "    █████              █████    ",
    "    █████              █████    ",
    "    ██████            ██████    ",
    "    ▀█████▄          ▄█████     ",
    "     ▀█████▄   ▄▄   ██████▀     ",
    "      ▀███▀  ▄████▄  ▀███▀      ",
    "        ▀  ▄████████▄  ▀        ",
    "          ████████████          ",
    "           ▀████████▀           ",
    "             ▀████▀             ",
    "               ▀▀               ",
]
HERO_GRADIENT = [LOGO_FG] * len(HERO_LINES)  # glyph only, no badge background


def rich_block(lines: list[str], grad: list[str]) -> str:
    return "\n".join(f"[{grad[i % len(grad)]}]{l}[/]" for i, l in enumerate(lines))


def ts_array(lines: list[str]) -> str:
    return "\n".join(f"  '{l}'," for l in lines).rstrip(",")


def sub_block(text: str, name: str, new_body: str) -> str:
    """Replace NAME = \"\"\"...\"\"\" (python) with new triple-quoted body."""
    rx = re.compile(rf'({re.escape(name)} = """)(.*?)(""")', re.DOTALL)
    return rx.sub(lambda m: m.group(1) + new_body + m.group(3), text, count=1)


def sub_ts_array(text: str, name: str, lines: list[str]) -> str:
    rx = re.compile(rf"(const {re.escape(name)} = \[\n)(.*?)(\n\])", re.DOTALL)
    return rx.sub(lambda m: m.group(1) + ts_array(lines) + m.group(3), text, count=1)


def main() -> int:
    changed = 0

    def write(p: Path, old: str, new: str):
        nonlocal changed
        if new != old:
            p.write_text(new, encoding="utf-8")
            changed += 1

    # 1) Logo + hero in CLI (banner.py, cli.py)
    for rel in ("nunmai_cli/banner.py", "cli.py"):
        p = ROOT / rel
        s = p.read_text(encoding="utf-8")
        n = sub_block(s, "NUNMAI_AGENT_LOGO", rich_block(LOGO_LINES, LOGO_GRADIENT))
        n = sub_block(n, "NUNMAI_CADUCEUS", rich_block(HERO_LINES, HERO_GRADIENT))
        write(p, s, n)

    # 2) Logo + hero in TUI
    p = ROOT / "ui-tui/src/banner.ts"
    s = p.read_text(encoding="utf-8")
    n = sub_ts_array(s, "LOGO_ART", LOGO_LINES)
    n = sub_ts_array(n, "CADUCEUS_ART", HERO_LINES)
    write(p, s, n)

    # 3) Tagline in classic banner
    p = ROOT / "cli.py"
    s = p.read_text(encoding="utf-8")
    n = s.replace('line1 = "⚕ NOUS NUNMAI - AI Agent Framework"', 'line1 = "✦ NUNMAI ENGINE - AI Engine by Nunmai Research"')
    n = n.replace('line1 = "✦ NOUS NUNMAI - AI Agent Framework"', 'line1 = "✦ NUNMAI ENGINE - AI Engine by Nunmai Research"')
    n = n.replace('tiny_line = "⚕ NOUS NUNMAI"', 'tiny_line = "✦ NUNMAI ENGINE"')
    n = n.replace('tiny_line = "✦ NOUS NUNMAI"', 'tiny_line = "✦ NUNMAI ENGINE"')
    write(p, s, n)

    p = ROOT / "nunmai_cli/skin_engine.py"
    s = p.read_text(encoding="utf-8")
    n = s.replace('"description": "Classic Nunmai — gold and kawaii"', '"description": "Nunmai — mint on deep green"')
    write(p, s, n)

    # 4) Symbol + palette sweep
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(ROOT).as_posix()
            if fn == "LICENSE" or rel.startswith("scripts/apply_nunmai_theme.py"):
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8000]:
                continue
            in_scope = rel.startswith(PALETTE_SCOPE)
            if "⚕".encode() not in data and not (in_scope and COLOR_RE.search(data.decode("utf-8", "ignore"))):
                continue
            try:
                s = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            n = s.replace("⚕", "✦")
            if in_scope:
                n = COLOR_RE.sub(lambda m: COLOR_MAP[m.group(0).upper()], n)
                n = n.replace("255;215;0m", "107;231;200m")  # _GOLD true-color -> mint
            write(p, s, n)

    print(f"nunmai theme applied: {changed} files changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
