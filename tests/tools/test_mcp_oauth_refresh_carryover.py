"""A refresh response without refresh_token must not lose the one on disk (Zoho MCP servers omit it)."""
import asyncio, json
import pytest

pytest.importorskip("mcp")


def test_set_tokens_keeps_previous_refresh_token(tmp_path):
    from tools import mcp_oauth
    from mcp.shared.auth import OAuthToken

    storage = mcp_oauth.NunmaiTokenStorage("srv", nunmai_home=tmp_path)
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a1", token_type="Bearer", expires_in=3600, refresh_token="r1")))
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a2", token_type="Bearer", expires_in=3600)))
    saved = json.load(open(tmp_path / "mcp-tokens" / "srv.json"))
    assert saved["access_token"] == "a2" and saved["refresh_token"] == "r1"
