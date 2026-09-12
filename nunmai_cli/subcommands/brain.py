"""``nunmai brain`` subcommand parser.

Nunmai's own command: pick the AI subscriptions or keys you already own and have them wired as a
primary model plus a fallback chain, in one step. First run calls the same wizard, so a fresh install
reaches a working model without hand-editing config.
"""

from __future__ import annotations

import argparse


def build_brain_parser(subparsers) -> None:
    """Attach the ``brain`` subcommand to ``subparsers``."""
    from nunmai_cli.brain_cmd import cmd_brain

    brain_parser = subparsers.add_parser(
        "brain",
        help="Connect your AI accounts (Claude, ChatGPT, Kimi, Gemini, OpenRouter) in one step",
        description="Pick the AI subscriptions/keys you own; Nunmai wires them as primary + fallback chain.",
    )
    brain_parser.add_argument(
        "--providers", help="Comma-separated provider ids in preference order (non-interactive)")
    brain_parser.add_argument("--skip-connect", action="store_true", help=argparse.SUPPRESS)
    brain_parser.set_defaults(func=cmd_brain)
