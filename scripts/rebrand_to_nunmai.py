#!/usr/bin/env python3
"""Rebrand the Hermes Agent source tree to Nunmai.

Runs from the repo root. Idempotent: safe to re-run after pulling upstream.

- Renames files/dirs containing "hermes" (any case) to "nunmai".
- Rewrites text content: Hermes->Nunmai, hermes->nunmai, HERMES->NUNMAI.
- Protects things that must NOT change:
    * LICENSE (MIT copyright notice must stay intact)
    * URLs / repo slugs pointing at Nous Research (docs, GitHub, HF)
    * Nous model IDs such as "hermes-4-405b", "NousResearch/Hermes-4"
    * Upstream contributor e-mails
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "build", ".next"}
SKIP_FILES = {"LICENSE", "rebrand_to_nunmai.py"}
SKIP_PATH_PREFIXES = ("contributors/",)

# Patterns to protect (case-insensitive). Each match is swapped for a sentinel
# before the brand replace and restored afterwards.
PROTECT = [
    r"https?://[^\s\"'<>)\]{}$]*hermes[^\s\"'<>)\]{}$]*",           # any URL containing hermes
    r"nousresearch/hermes[\w.\-]*",                             # GitHub/HF repo slugs
    r"hermes-agent\.nousresearch\.com",
    r"hermes-agent\.org",
    r"hermes[-_ ]?[34](?:[-_.][\w]+)*",                         # model ids: hermes-4-405b, Hermes 3, hermes_4
    r"hermes\[-_ \]\?\[34\]",                                # the regex SOURCE that matches those ids (model_switch.py)
    r"deephermes[\w.\-]*",                                      # DeepHermes model family
    r"[\w.+\-]+@[\w.\-]*hermes[\w.\-]*",                        # e-mail addresses
]
PROTECT_RE = re.compile("|".join(f"(?:{p})" for p in PROTECT), re.IGNORECASE)

# Applied AFTER protected spans are restored: company name + public web hosts.
# Functional Nous hosts (portal., inference-api., gateway., agents., api.,
# tool-gateway., staging) and github.com/NousResearch are deliberately kept
# so login, inference, update-check and skills-hub keep working.
POST_REPLACEMENTS = [
    # Dockerfile SQLite FTS5 self-test: trigram 'erm' is a substring of 'hermes'; after the
    # row becomes 'nunmai' the probe must search a substring of 'nunmai'.
    (re.compile(r"MATCH 'erm'"), "MATCH 'unm'"),
    (re.compile(r"https://setup\.hermes-agent\.nousresearch\.com"), "https://setup.nunmai.in"),
    (re.compile(r"https://hermes-agent\.nousresearch\.com(?!/docs/api/skills-index\.json)"), "https://nunmai.in"),
    (re.compile(r"https://nousresearch\.com(?![\w-]|\.[\w-])"), "https://nunmai.in"),
    (re.compile(r"Nous Research"), "Nunmai Research"),
    # Installer / updater clone URLs -> Nunmai's own repo (override org here)
    (re.compile(r"git@github\.com:NousResearch/hermes-agent\.git"), "git@github.com:Nunmai-Private-Limited/nunmai-engine.git"),
    (re.compile(r"https://github\.com/NousResearch/hermes-agent\.git"), "https://github.com/Nunmai-Private-Limited/nunmai-engine.git"),
    # Update-check / release endpoints -> Nunmai repo (docker image + issue links stay upstream)
    (re.compile(r"api\.github\.com/repos/nousresearch/hermes-agent"), "api.github.com/repos/Nunmai-Private-Limited/nunmai-engine"),
    (re.compile(r'"github\.com/nousresearch/hermes-agent"'), '"github.com/nunmai-private-limited/nunmai-engine"'),
    (re.compile(r"https://github\.com/NousResearch/hermes-agent/releases"), "https://github.com/Nunmai-Private-Limited/nunmai-engine/releases"),
    # One-line installer host
    (re.compile(r"https://nunmai\.in/install\.(sh|ps1)"), r"https://nunmai-engine.nunmai.in/install.\1"),
]

REPLACEMENTS = [
    (re.compile(r"HERMES"), "NUNMAI"),
    (re.compile(r"Hermes"), "Nunmai"),
    (re.compile(r"hermes"), "nunmai"),
    # Product name: "Nunmai Engine" (CLI stays `nunmai`)
    (re.compile(r"Nunmai Agent"), "Nunmai Engine"),
    (re.compile(r"NUNMAI AGENT"), "NUNMAI ENGINE"),
    (re.compile(r"nunmai-agent"), "nunmai-engine"),
]


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8000]


def rebrand_text(text: str) -> str:
    keep: list[str] = []

    def stash(m: re.Match) -> str:
        keep.append(m.group(0))
        return f"\x00KEEP{len(keep) - 1}\x00"

    text = PROTECT_RE.sub(stash, text)
    for rx, rep in REPLACEMENTS:
        text = rx.sub(rep, text)
    text = re.sub(r"\x00KEEP(\d+)\x00", lambda m: keep[int(m.group(1))], text)
    for rx, rep in POST_REPLACEMENTS:
        text = rx.sub(rep, text)
    return text


def rename_path_part(name: str) -> str:
    return name.replace("HERMES", "NUNMAI").replace("Hermes", "Nunmai").replace("hermes", "nunmai")


def main() -> int:
    changed_files = renamed = 0
    # 1) content
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, ROOT)
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            rel = os.path.normpath(os.path.join(rel_dir, fn))
            if rel.startswith(SKIP_PATH_PREFIXES):
                continue
            p = Path(dirpath) / fn
            if p.is_symlink():
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            if is_binary(data) or not re.search(rb"hermes|nunmai[ -]agent|nous", data, re.IGNORECASE):
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            new = rebrand_text(text)
            if new != text:
                p.write_text(new, encoding="utf-8")
                changed_files += 1
    # 2) paths (deepest first so parents rename after children)
    paths = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for n in dirnames + filenames:
            if "hermes" in n.lower():
                paths.append(Path(dirpath) / n)
    for p in sorted(paths, key=lambda x: len(x.parts), reverse=True):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PATH_PREFIXES):
            continue
        target = p.with_name(rename_path_part(p.name))
        if target.exists():
            print(f"!! target exists, skipping: {target}", file=sys.stderr)
            continue
        p.rename(target)
        renamed += 1
    print(f"rebrand done: {changed_files} files rewritten, {renamed} paths renamed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
