"""X-Nunmai-Toolsets '-<toolset>' entries (Nunmai Platform owner-guarded agents): a request can switch enabled built-in
toolsets off for itself, never on."""
from gateway.platforms.api_server import _apply_request_toolsets

ENABLED = ["web", "memory", "skills", "todo", "clarify", "session_search", "terminal", "file", "browser", "mcp-inside__zoho-books"]


def test_minus_entries_remove_built_in_toolsets_for_this_request():
    out = _apply_request_toolsets(ENABLED, ["mcp-inside__zoho-books", "-terminal", "-file", "-browser", "-memory", "-skills", "-session_search"], "inside")
    assert out == sorted(["web", "todo", "clarify", "mcp-inside__zoho-books"])


def test_minus_entries_never_add_anything():
    out = _apply_request_toolsets(["web"], ["-terminal", "-web-unknown"], "inside")
    assert out == ["web"]


def test_without_minus_entries_nothing_changes():
    assert _apply_request_toolsets(ENABLED, ["mcp-inside__zoho-books"], "inside") == sorted(ENABLED)
