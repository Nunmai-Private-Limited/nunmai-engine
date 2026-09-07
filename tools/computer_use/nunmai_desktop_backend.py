"""computer_use backend for a Nunmai agent desktop that another service owns.

The Nunmai platform runs one Xfce desktop per agent (Xvfb + x11vnc, driven by the meeting bot) and links the engine
session of every chat turn to that desktop. This backend forwards computer_use actions over HTTP to that service, which
resolves the session id to the right X display and performs them with ffmpeg (capture) and xdotool (input).

Selected with NUNMAI_COMPUTER_USE_BACKEND=nunmai-desktop; needs NUNMAI_DESKTOP_CONTROL_URL (the service, e.g.
http://127.0.0.1:3200) and NUNMAI_DESKTOP_CONTROL_KEY (its shared key). Captures come back as JPEG at a fixed scale
(long edge 1440) with elements=[] (vision mode): the model works from the picture and clicks by coordinates in that
picture; the service maps them back to the real screen.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from tools.computer_use.backend import ActionResult, CaptureResult, ComputerUseBackend

BACKEND_NAME = "nunmai-desktop"
_URL_ENV = "NUNMAI_DESKTOP_CONTROL_URL"
_KEY_ENV = "NUNMAI_DESKTOP_CONTROL_KEY"


def nunmai_desktop_configured() -> bool:
    return bool(os.environ.get(_URL_ENV, "").strip() and os.environ.get(_KEY_ENV, "").strip())


def _session_id() -> str:
    try:
        from gateway.session_context import get_session_env
        sid = get_session_env("NUNMAI_SESSION_ID", "") or ""
    except Exception:
        sid = ""
    return sid or os.environ.get("NUNMAI_SESSION_ID", "") or ""


class NunmaiDesktopBackend(ComputerUseBackend):
    def __init__(self, permission_mode: str = "standard"):
        self.permission_mode = permission_mode
        self._last_app = None

    # ---- lifecycle ----
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_available(self) -> bool: return nunmai_desktop_configured()

    # ---- transport ----
    def _call(self, action: str, **args: Any) -> Dict[str, Any]:
        base = os.environ.get(_URL_ENV, "").rstrip("/")
        key = os.environ.get(_KEY_ENV, "")
        sid = _session_id()
        body = json.dumps({"session_id": sid, "action": action, "args": args}).encode()
        req = urllib.request.Request(f"{base}/desktop-control", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Hub-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try: detail = json.loads(e.read().decode()).get("detail")
            except Exception: detail = None
            return {"ok": False, "error": str(detail or e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _result(self, action: str, r: Dict[str, Any]) -> ActionResult:
        if r.get("ok"):
            return ActionResult(ok=True, action=action, message=str(r.get("message") or "done"), meta={k: v for k, v in r.items() if k not in ("ok", "message") and v is not None})
        return ActionResult(ok=False, action=action, message=str(r.get("error") or "failed"), code="desktop_control_error")

    # ---- capture ----
    def capture(self, mode: str = "som", app: Optional[str] = None, pid: Optional[int] = None, window_id: Optional[int] = None) -> CaptureResult:
        r = self._call("capture")
        if not r.get("ok"):
            raise RuntimeError(r.get("error") or "capture failed")
        return CaptureResult(mode="vision", width=int(r.get("width") or 0), height=int(r.get("height") or 0), png_b64=r.get("image_b64"),
                             elements=[], app=str(r.get("app") or ""), window_title=str(r.get("window_title") or ""),
                             png_bytes_len=int(r.get("bytes") or 0), image_mime_type=r.get("mime") or "image/jpeg",
                             note="No element list on this desktop: read the picture and act by coordinates in it (click/drag/scroll with coordinate=[x,y]).")

    # ---- pointer ----
    def click(self, *, element=None, x=None, y=None, button="left", click_count=1, modifiers=None, delivery_mode=None, bring_to_front=False) -> ActionResult:
        if x is None or y is None:
            return ActionResult(ok=False, action="click", message="this desktop has no element list; pass coordinate=[x,y] from the last capture", code="needs_coordinates")
        return self._result("click", self._call("click", x=int(x), y=int(y), button=button, count=int(click_count or 1), modifiers=list(modifiers or [])))

    def drag(self, *, from_element=None, to_element=None, from_xy=None, to_xy=None, button="left", modifiers=None, delivery_mode=None, bring_to_front=False) -> ActionResult:
        if not from_xy or not to_xy:
            return ActionResult(ok=False, action="drag", message="pass from_coordinate and to_coordinate", code="needs_coordinates")
        return self._result("drag", self._call("drag", x1=int(from_xy[0]), y1=int(from_xy[1]), x2=int(to_xy[0]), y2=int(to_xy[1]), button=button))

    def scroll(self, *, direction, amount=3, element=None, x=None, y=None, modifiers=None, delivery_mode=None, bring_to_front=False) -> ActionResult:
        return self._result("scroll", self._call("scroll", direction=direction, amount=int(amount or 3), x=x, y=y))

    # ---- keyboard ----
    def type_text(self, text: str, *, delivery_mode=None, bring_to_front=False) -> ActionResult:
        return self._result("type", self._call("type", text=text))

    def key(self, keys: str, *, delivery_mode=None, bring_to_front=False) -> ActionResult:
        return self._result("key", self._call("key", keys=keys))

    # ---- introspection ----
    def list_apps(self) -> List[Dict[str, Any]]:
        r = self._call("list_apps")
        return list(r.get("apps") or []) if r.get("ok") else []

    def list_windows(self) -> List[Dict[str, Any]]:
        r = self._call("list_windows")
        return list(r.get("windows") or []) if r.get("ok") else []

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        self._last_app = app
        return self._result("focus", self._call("focus", app=app))

    def set_value(self, value: str, element: Optional[int] = None) -> ActionResult:
        return ActionResult(ok=False, action="set_value", message="not supported on this desktop; click the field and type instead", code="unsupported")
