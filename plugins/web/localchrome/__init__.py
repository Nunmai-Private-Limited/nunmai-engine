"""Local Chrome extract-only plugin (agent-browser CLI) — bundled, auto-loaded."""
from __future__ import annotations
from plugins.web.localchrome.provider import LocalChromeWebProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(LocalChromeWebProvider())
