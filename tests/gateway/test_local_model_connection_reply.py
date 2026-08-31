"""Regression tests for #86570: gateway provider error connection messaging."""

import pytest

from gateway.run import (
    _GATEWAY_CONNECTION_ERROR_RE,
    _gateway_provider_error_reply,
    _looks_like_gateway_provider_error,
)


class TestGatewayConnectionErrorReply:
    def test_connection_error_strings_produce_customer_safe_reply(self):
        samples = [
            "openai.APIConnectionError",
            "httpx.ConnectError: connection refused",
            "ConnectionError: [WinError 10061] No connection could be made",
            "Errno 111 Connection refused",
            "All connection attempts failed: Connection refused",
        ]
        for text in samples:
            assert _looks_like_gateway_provider_error(text), text
            reply = _gateway_provider_error_reply(text)
            assert "try again" in reply.lower(), text
            assert "conversation is safe" in reply.lower(), text

    def test_broad_connection_phrases_are_customer_safe_once_classified(self):
        for text in (
            "cannot connect to http://127.0.0.1:8033/v1",
            "failed to establish a new connection",
        ):
            reply = _gateway_provider_error_reply(text)
            assert "try again" in reply.lower(), text
            assert "provider" not in reply.lower(), text
            assert "gateway" not in reply.lower(), text
            assert "logs" not in reply.lower(), text

    def test_prose_cannot_connect_is_not_a_provider_error(self):
        text = (
            "cannot connect to the office VPN from this cafe, "
            "so I used the backup notes instead"
        )
        assert not _looks_like_gateway_provider_error(text)

    def test_other_errors_keep_generic_reply(self):
        for text in (
            "RuntimeError: model returned empty content",
            "Exception: unknown provider",
            "HTTP 500 internal server error",
        ):
            if _looks_like_gateway_provider_error(text):
                reply = _gateway_provider_error_reply(text)
                assert "not running or is unreachable" not in reply, text

    def test_connection_regex_does_not_match_non_connection_error(self):
        assert not _GATEWAY_CONNECTION_ERROR_RE.search("Rate limited after 3 retries")
        assert not _GATEWAY_CONNECTION_ERROR_RE.search("Provider authentication failed")

    def test_auth_and_rate_limit_are_customer_safe(self):
        for text in (
            "provider authentication failed",
            "rate limited after 3 retries",
        ):
            reply = _gateway_provider_error_reply(text)
            assert "try again" in reply.lower()
            assert "conversation is safe" in reply.lower()
            for internal_term in ("provider", "gateway", "logs", "retries"):
                assert internal_term not in reply.lower()

    def test_policy_rejection_is_customer_safe(self):
        reply = _gateway_provider_error_reply("request was rejected")
        assert "rephrasing" in reply.lower()
        assert "provider" not in reply.lower()
        assert "logs" not in reply.lower()

    def test_exhausted_provider_reply_is_customer_safe(self):
        reply = _gateway_provider_error_reply(
            "API call failed after retries: HTTP 500 internal server error"
        )
        lower = reply.lower()
        assert "try again" in lower
        assert "conversation is safe" in lower
        for internal_term in ("provider", "gateway", "logs", "retries", "diagnostics"):
            assert internal_term not in lower
