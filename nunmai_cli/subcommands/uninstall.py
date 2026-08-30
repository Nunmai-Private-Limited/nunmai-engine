"""``nunmai uninstall`` subcommand parser.

Extracted verbatim from ``nunmai_cli/main.py:main()`` (god-file Phase 2).
Handler injected to avoid importing ``main``.
"""

from __future__ import annotations

import argparse
from typing import Callable


def build_uninstall_parser(subparsers, *, cmd_uninstall: Callable) -> None:
    """Attach the ``uninstall`` subcommand to ``subparsers``."""
    # =========================================================================
    # uninstall command
    # =========================================================================
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Uninstall Nunmai Engine",
        description=(
            "Remove Nunmai Engine and everything it installed: the engine, "
            "~/.nunmai (config, API keys, sessions, logs, managed Node/uv), the "
            "gateway service, the `nunmai` command, browser/uv caches and the "
            "npm package. Use --keep-data to keep ~/.nunmai for a later reinstall."
        ),
    )
    uninstall_parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep ~/.nunmai (config, API keys, sessions, logs) so a reinstall picks them back up",
    )
    # Legacy flag: a clean, complete removal is now the default, so --full is
    # accepted silently for scripts and docs that still pass it.
    uninstall_parser.add_argument("--full", action="store_true", help=argparse.SUPPRESS)
    uninstall_parser.add_argument(
        "--gui",
        action="store_true",
        help="Uninstall only the desktop Chat GUI, leaving the agent intact",
    )
    uninstall_parser.add_argument(
        "--gui-summary",
        action="store_true",
        help="Print a JSON summary of installed GUI/agent artifacts and exit "
        "(used by the desktop app to gate uninstall options)",
    )
    uninstall_parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompts"
    )
    uninstall_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what uninstall would remove without changing anything",
    )
    uninstall_parser.set_defaults(func=cmd_uninstall)
