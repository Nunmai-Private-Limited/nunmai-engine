"""Resolve NUNMAI_HOME for standalone skill scripts.

Skill scripts may run outside the Nunmai process (system Python, nix env,
CI) where ``nunmai_constants`` is not importable.  This module provides the
same ``get_nunmai_home()`` contract without requiring it on ``sys.path``.

When ``nunmai_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from nunmai_constants import get_nunmai_home as get_nunmai_home
except (ModuleNotFoundError, ImportError):

    def get_nunmai_home() -> Path:
        """Return the Nunmai home directory (default: ``~/.nunmai``)."""
        val = os.environ.get("NUNMAI_HOME", "").strip()
        return Path(val) if val else Path.home() / ".nunmai"
