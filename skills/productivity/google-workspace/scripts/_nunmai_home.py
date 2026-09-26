"""Resolve NUNMAI_HOME for standalone skill scripts.

Skill scripts may run outside the Nunmai process (e.g. system Python,
nix env, CI) where ``nunmai_constants`` is not importable.  This module
provides the same ``get_nunmai_home()`` and ``display_nunmai_home()``
contracts as ``nunmai_constants`` without requiring it on ``sys.path``.

When ``nunmai_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``nunmai_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``NUNMAI_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from nunmai_constants import display_nunmai_home as display_nunmai_home
    from nunmai_constants import get_nunmai_home as get_nunmai_home
except (ModuleNotFoundError, ImportError):

    def get_nunmai_home() -> Path:
        """Return the Nunmai home directory (default: ~/.nunmai).

        Mirrors ``nunmai_constants.get_nunmai_home()``."""
        val = os.environ.get("NUNMAI_HOME", "").strip()
        return Path(val) if val else Path.home() / ".nunmai"

    def display_nunmai_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``nunmai_constants.display_nunmai_home()``."""
        home = get_nunmai_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)
