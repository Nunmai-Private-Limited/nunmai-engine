"""Model router — pure routing logic (no plugin glue).

Given the text of an incoming user turn, decide which *tier* it belongs to
and which provider/model should run it:

* ``simple``  — greetings, thanks, yes/no, tiny factual questions → fast model
* ``normal``  — everyday questions and short tasks → the main model
* ``complex`` — multi-step engineering work, debugging, code changes,
  deployments, analysis → the Nunmai Agent orchestrator (``moa`` provider)

Two stages: cheap regex heuristics catch the obvious ends of the spectrum
without any model call; the middle band is classified by a fast auxiliary
model (task ``model_router``).  Every failure path falls back to ``normal`` so
a broken classifier can never take the agent offline.

Everything in here is deliberately side-effect free and testable: the plugin
``__init__`` wires it to the ``resolve_turn_model`` hook.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Optional

logger = logging.getLogger("nunmai.model_router")

TIERS = ("simple", "normal", "complex")
AUX_TASK = "model_router"

# Curated fast siblings for providers whose catalogs the auxiliary fast-model
# ladder cannot see (Codex models are excluded from that ladder on purpose).
FAST_MODEL_BY_PROVIDER: Dict[str, str] = {
    "openai-codex": "gpt-5.4-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-5-mini",
    "copilot": "gpt-5-mini",
}

MOA_VIRTUAL_RUNTIME = {
    "provider": "moa",
    "base_url": "moa://local",
    "api_key": "moa-virtual-provider",
    "api_mode": "chat_completions",
}

_MOA_MARKER_PREFIX = "__NUNMAI_MOA_TURN_V1__"

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|hai|hola|salam|salaam|assalamu ?alaikum|as-salamu alaykum|"
    r"good (morning|afternoon|evening|night)|thanks?|thank you|thx|ty|ok|okay|okey|"
    r"yes|no|yep|nope|sure|great|nice|cool|fine|done|got it|noted|welcome|bye|"
    r"good ?bye|see you|who are you|what can you do|help|ping|test|testing|"
    r"how are you|are you (there|online|awake)|what'?s up|hru)"
    r"[\s!.?,]*$",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"```|\b(def |class |import |from \w+ import|SELECT |INSERT |UPDATE |DELETE |"
    r"function\s*\(|=>|#!/|\$\{|<\?php|npm |pip |docker |kubectl |git |systemctl )",
)
_COMPLEX_KW_RE = re.compile(
    r"\b(implement|refactor|debug|deploy|deployment|migrate|migration|architect|"
    r"architecture|design (a|the|an)|investigate|root cause|rca|compare|plan|roadmap|"
    r"step[- ]by[- ]step|analy[sz]e|analysis|audit|optimi[sz]e|benchmark|integrat(e|ion)|"
    r"pipeline|ci/cd|stack ?trace|traceback|exception|failing|broken|not working|"
    r"pull request|merge|release|rollback|incident|outage|security|vulnerab|"
    r"write (a|the|an|me) (script|module|function|class|service|api|test)|"
    r"build (a|the|an|me)|create (a|the|an|me) (script|module|function|class|service|api|app))\b",
    re.IGNORECASE,
)
_PATH_OR_URL_RE = re.compile(r"https?://|/[\w.-]+/[\w.-]+|\w+\.(py|js|ts|yaml|yml|json|php|sql|md)\b")


@dataclass
class Decision:
    tier: str
    reason: str
    via: str  # "heuristic" | "classifier" | "fallback" | "skip"
    target: Optional[Dict[str, str]] = None
    ts: float = field(default_factory=time.time)


def strip_markers(text: str) -> str:
    """Drop the hidden MoA-turn marker so it never confuses classification."""
    if text.startswith(_MOA_MARKER_PREFIX):
        nl = text.find("\n")
        return text[nl + 1:] if nl >= 0 else ""
    return text


def should_skip(text: Optional[str]) -> Optional[str]:
    """Return a skip reason for turns the router must never touch."""
    if not isinstance(text, str):
        return "non-text"
    t = text.strip()
    if not t:
        return "empty"
    if t.startswith("/"):
        return "slash-command"
    if t.startswith(_MOA_MARKER_PREFIX):
        return "moa-marker"
    return None


def classify_heuristic(text: str) -> Optional[Decision]:
    """Fast, model-free classification of the obvious cases.

    Returns ``None`` when the message sits in the ambiguous middle band.
    """
    t = strip_markers(text).strip()
    words = t.split()
    n_words = len(words)
    n_lines = t.count("\n") + 1
    has_code = bool(_CODE_RE.search(t))
    has_path = bool(_PATH_OR_URL_RE.search(t))

    if has_code or n_lines >= 6 or len(t) > 800:
        return Decision("complex", "code/long/multi-line", "heuristic")
    if _COMPLEX_KW_RE.search(t) and (n_words >= 6 or has_path):
        return Decision("complex", "engineering keywords", "heuristic")
    if n_words <= 8 and not has_path and _GREETING_RE.match(t):
        return Decision("simple", "greeting/ack", "heuristic")
    if n_words <= 3 and not has_path and not t.endswith("?"):
        return Decision("simple", "very short", "heuristic")
    return None


_CLASSIFIER_SYSTEM = (
    "You are a routing classifier for an AI assistant. Decide how much reasoning the "
    "user's message needs and reply with exactly ONE word.\n"
    "SIMPLE: greetings, thanks, small talk, yes/no, acknowledgements, trivial factual "
    "questions, short status questions that need no tools.\n"
    "NORMAL: ordinary questions, explanations, summaries, short single-step tasks, "
    "quick lookups, simple edits.\n"
    "COMPLEX: multi-step engineering work, debugging, code changes, deployments, "
    "infrastructure, architecture, comparisons across several sources, planning, "
    "anything that needs careful reasoning or several tool calls.\n"
    "Answer with SIMPLE, NORMAL or COMPLEX only."
)


def parse_tier(raw: Any) -> Optional[str]:
    """Extract a tier name from a classifier reply; ``None`` if unparseable."""
    if not isinstance(raw, str):
        return None
    m = re.search(r"\b(simple|normal|complex)\b", raw, re.IGNORECASE)
    return m.group(1).lower() if m else None


def classify(
    text: str,
    *,
    mode: str = "auto",
    llm: Optional[Callable[[str], Any]] = None,
    max_chars: int = 2000,
) -> Decision:
    """Full classification: heuristics first, classifier for the middle band."""
    decision = classify_heuristic(text)
    if decision is not None:
        return decision
    if mode != "auto" or llm is None:
        return Decision("normal", "middle band (no classifier)", "fallback")
    snippet = strip_markers(text).strip()[:max_chars]
    try:
        raw = llm(snippet)
    except Exception as exc:  # classifier problems must never block the turn
        logger.debug("model_router classifier failed: %s", exc)
        return Decision("normal", f"classifier error: {type(exc).__name__}", "fallback")
    tier = parse_tier(raw)
    if tier is None:
        return Decision("normal", "classifier reply unparseable", "fallback")
    return Decision(tier, "classifier", "classifier")


# --------------------------------------------------------------------------
# Tier → provider/model target resolution
# --------------------------------------------------------------------------

def _main_single_model(config: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The main *single* model: config ``model`` or, for MoA, the aggregator."""
    model_cfg = (config or {}).get("model") or {}
    provider = str(model_cfg.get("provider") or "").strip()
    model = str(model_cfg.get("default") or "").strip()
    if not provider or not model:
        return None
    if provider.lower() != "moa":
        return {"provider": provider, "model": model}
    try:
        from nunmai_cli.moa_config import resolve_moa_preset

        preset = resolve_moa_preset((config or {}).get("moa"), model)
        agg = preset.get("aggregator") or {}
        if agg.get("provider") and agg.get("model"):
            return {"provider": str(agg["provider"]), "model": str(agg["model"])}
    except Exception:
        logger.debug("model_router: could not resolve MoA aggregator", exc_info=True)
    return None


def fast_model_for(provider: str) -> Optional[str]:
    """Best-effort fast sibling for *provider* (curated map, then aux ladder)."""
    if provider in FAST_MODEL_BY_PROVIDER:
        return FAST_MODEL_BY_PROVIDER[provider]
    try:
        from agent.auxiliary_client import _get_aux_model_for_provider

        return _get_aux_model_for_provider(provider, prefer_fast=True) or None
    except Exception:
        return None


def default_tiers(config: Dict[str, Any]) -> Dict[str, Optional[Dict[str, str]]]:
    """Derive tier targets from the main model when none are configured."""
    main = _main_single_model(config)
    tiers: Dict[str, Optional[Dict[str, str]]] = {"simple": None, "normal": None, "complex": None}
    if main:
        tiers["normal"] = dict(main)
        fast = fast_model_for(main["provider"])
        if fast and fast != main["model"]:
            tiers["simple"] = {"provider": main["provider"], "model": fast}
    try:
        from nunmai_cli.moa_config import normalize_moa_config

        moa_cfg = normalize_moa_config((config or {}).get("moa") or {})
        preset = str(moa_cfg.get("default_preset") or "default")
        tiers["complex"] = {"provider": "moa", "model": preset}
    except Exception:
        tiers["complex"] = {"provider": "moa", "model": "default"}
    return tiers


def resolve_tiers(settings: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Optional[Dict[str, str]]]:
    """Merge user-configured tiers over the derived defaults."""
    tiers = default_tiers(config)
    raw = (settings or {}).get("tiers") or {}
    if isinstance(raw, dict):
        for name in TIERS:
            spec = raw.get(name)
            if isinstance(spec, dict) and spec.get("provider") and spec.get("model"):
                tiers[name] = {"provider": str(spec["provider"]), "model": str(spec["model"])}
            elif spec in (None, "", False) and name in raw:
                tiers[name] = None  # explicitly disabled tier
    return tiers


class OverrideResolver:
    """Turn a (provider, model) target into a runtime override, with caching.

    Credential resolution goes through :func:`nunmai_cli.model_switch.switch_model`
    — the same pipeline ``/model`` uses — so OAuth pools, API keys and custom
    providers all behave exactly as a manual switch would.
    """

    def __init__(self, ttl: float = 300.0):
        self._ttl = ttl
        self._cache: Dict[tuple, tuple] = {}
        self._lock = threading.Lock()

    def resolve(
        self,
        target: Dict[str, str],
        *,
        current_model: str,
        current_runtime: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        provider = target["provider"]
        model = target["model"]
        if provider == "moa":
            return {"model": model, "runtime": dict(MOA_VIRTUAL_RUNTIME)}
        key = (provider, model)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self._ttl:
                return dict(hit[1]) if hit[1] else None
        override = self._resolve_uncached(provider, model, current_model, current_runtime, config)
        with self._lock:
            self._cache[key] = (now, dict(override) if override else None)
        return override

    @staticmethod
    def _resolve_uncached(provider, model, current_model, current_runtime, config):
        try:
            from nunmai_cli.model_switch import switch_model

            custom = None
            try:
                from nunmai_cli.config import get_compatible_custom_providers

                custom = get_compatible_custom_providers(config)
            except Exception:
                custom = (config or {}).get("custom_providers")
            result = switch_model(
                raw_input=model,
                current_provider=str(current_runtime.get("provider") or ""),
                current_model=str(current_model or ""),
                current_base_url=str(current_runtime.get("base_url") or ""),
                current_api_key=str(current_runtime.get("api_key") or ""),
                is_global=False,
                explicit_provider=provider,
                user_providers=(config or {}).get("providers"),
                custom_providers=custom,
            )
        except Exception as exc:
            logger.warning("model_router: credential resolution for %s/%s failed: %s", provider, model, exc)
            return None
        if not getattr(result, "success", False):
            logger.warning(
                "model_router: cannot switch to %s/%s: %s",
                provider, model, getattr(result, "error_message", "") or "unknown error",
            )
            return None
        return {
            "model": result.new_model or model,
            "runtime": {
                "provider": result.target_provider or provider,
                "api_key": result.api_key or "",
                "base_url": result.base_url or "",
                "api_mode": result.api_mode or "",
            },
        }


class Router:
    """Stateful facade used by the plugin: settings + history + resolver."""

    def __init__(self, *, settings_getter: Callable[[str, Any], Any], config_loader: Callable[[], Dict[str, Any]],
                 llm: Optional[Callable[[str], Any]] = None, history: int = 20):
        self._settings = settings_getter
        self._load_config = config_loader
        self._llm = llm
        self._resolver = OverrideResolver()
        self.history: Deque[Decision] = deque(maxlen=history)

    # -- settings -------------------------------------------------------
    @property
    def mode(self) -> str:
        if not self._settings("enabled", True):
            return "off"
        mode = str(self._settings("mode", "auto") or "auto").strip().lower()
        return mode if mode in ("auto", "heuristic", "off") else "auto"

    def tiers(self) -> Dict[str, Optional[Dict[str, str]]]:
        settings = {"tiers": self._settings("tiers", None)}
        return resolve_tiers(settings, self._load_config() or {})

    # -- main entry -----------------------------------------------------
    def route(
        self,
        text: Optional[str],
        *,
        current_model: str,
        current_runtime: Dict[str, Any],
        has_session_override: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return ``{"model", "runtime", "reason"}`` for this turn, or ``None``."""
        mode = self.mode
        if mode == "off":
            return None
        skip = should_skip(text)
        if skip:
            return None
        if has_session_override and self._settings("respect_session_override", True):
            self.history.append(Decision("normal", "session /model override active", "skip"))
            return None

        decision = classify(text, mode=mode, llm=self._llm if mode == "auto" else None)
        tiers = self.tiers()
        target = tiers.get(decision.tier)
        if target is None and decision.tier == "simple":
            target = tiers.get("normal")  # no fast sibling → main model
        decision.target = target
        self.history.append(decision)
        if not target:
            return None

        cur_provider = str(current_runtime.get("provider") or "")
        if target["provider"] == cur_provider and target["model"] == str(current_model or ""):
            return None  # already on the right brain — nothing to switch

        override = self._resolver.resolve(
            target,
            current_model=current_model,
            current_runtime=current_runtime,
            config=self._load_config() or {},
        )
        if not override:
            return None
        override["reason"] = f"{decision.tier} ({decision.via}: {decision.reason})"
        logger.info(
            "model_router: %s → %s/%s [%s]",
            decision.tier, override["runtime"].get("provider"), override["model"], decision.reason,
        )
        return override
