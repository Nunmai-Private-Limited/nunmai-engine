"""Extract via a headless Chromium on this machine, driven by the agent-browser CLI.

Extract-only: pair it with a search backend (``web.search_backend: searxng``, ``web.extract_backend: localchrome``).
Each URL gets its own short-lived agent-browser session: open, let the scripts run, read the title and the
body text, close. Shop pages (eXtra, Jarir, noon) render prices client-side, so a plain HTTP fetch returns the
product names with no prices; a real render returns both.

Safety: web_extract_tool refuses private-network URLs before this runs; a redirect that lands on one is caught
here from the final URL and its content is dropped. The subprocess gets the credential-scrubbed environment every
other agent-browser spawn uses.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import uuid
from typing import Any, Dict, List

from plugins.web._common import BaseWebSearchProvider, document, page_error, setup_schema

logger = logging.getLogger(__name__)

_OPEN_TIMEOUT = 60
_SETTLE_MS = 3000          # client-side rendering (prices, lazy product grids) after the load event
_MAX_CONCURRENT = 3


def _bin() -> str | None:
    return shutil.which("agent-browser")


def _env() -> dict:
    try:
        from tools.browser_tool import _build_browser_env
        return _build_browser_env()
    except Exception:  # noqa: BLE001 — stripped installs
        from tools.environments.local import nunmai_subprocess_env
        return nunmai_subprocess_env(inherit_credentials=False)


def _run(binary: str, session: str, args: List[str], timeout: int) -> str:
    r = subprocess.run([binary, "--session", session, *args], capture_output=True, text=True, timeout=timeout, env=_env())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or f"exit {r.returncode}").strip()[:300])
    return r.stdout


def _read_one(url: str) -> Dict[str, Any]:
    binary = _bin()
    if not binary:
        return page_error(url, "agent-browser is not installed on this machine")
    from tools.url_safety import is_safe_url
    if not is_safe_url(url):        # web_extract_tool already refuses these; kept so the provider is safe on its own
        return page_error(url, "Blocked: URL targets a private or internal address")
    session = f"wx-{uuid.uuid4().hex[:10]}"
    try:
        _run(binary, session, ["open", url], _OPEN_TIMEOUT)
        _run(binary, session, ["wait", str(_SETTLE_MS)], 30)
        final = _run(binary, session, ["get", "url"], 15).strip() or url
        if final != url and not is_safe_url(final):
            return page_error(url, "Blocked: redirect landed on a private or internal address")
        title = _run(binary, session, ["get", "title"], 15).strip()
        text = _run(binary, session, ["get", "text", "body"], 30).strip()
        if not text:
            return page_error(url, "The page rendered no text")
        logger.info("Local Chrome read %s: %d chars", url, len(text))
        return document(url, title, text, source_url=final)
    except subprocess.TimeoutExpired:
        return page_error(url, "Timed out loading the page in local Chrome")
    except Exception as e:  # noqa: BLE001 — one bad URL never fails the batch
        return page_error(url, f"Local Chrome could not read the page: {e}")
    finally:
        try:
            subprocess.run([binary, "--session", session, "close"], capture_output=True, timeout=15, env=_env())
        except Exception:  # noqa: BLE001
            pass


class LocalChromeWebProvider(BaseWebSearchProvider):
    """Extract-only provider backed by a local headless Chromium."""

    NAME = "localchrome"
    DISPLAY_NAME = "Local Chrome"
    KEY_ENV = ""
    EXTRACT = True

    def is_available(self) -> bool:
        return _bin() is not None

    def supports_search(self) -> bool:
        return False

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        from tools.interrupt import is_interrupted
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def one(u: str) -> Dict[str, Any]:
            if is_interrupted():
                return page_error(u, "Interrupted")
            async with sem:
                return await asyncio.to_thread(_read_one, u)

        return list(await asyncio.gather(*(one(u) for u in urls)))

    def get_setup_schema(self) -> Dict[str, Any]:
        return setup_schema("Local Chrome", "free · local", "Reads pages in a headless Chromium on this machine (extract only; needs agent-browser).")
