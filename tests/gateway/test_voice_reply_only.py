"""voice.voice_reply_only: a delivered voice note replaces the text bubble.

When the flag is pushed onto the adapter and the auto-TTS audio actually
reaches the chat, the separate text send is skipped. If TTS fails (or the
flag is off), the text is sent as usual so the answer is never lost.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)
from gateway.session import SessionSource, build_session_key


class _DummyAdapter(BasePlatformAdapter):
    def __init__(self, platform: Platform = Platform.WHATSAPP):
        super().__init__(PlatformConfig(enabled=True, token="fake-token"), platform)
        self.sent = []

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id, content, reply_to=None, metadata=None) -> SendResult:
        self.sent.append({"chat_id": chat_id, "content": content})
        return SendResult(success=True, message_id="1")

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def stop_typing(self, chat_id: str, metadata=None) -> None:
        return None

    async def get_chat_info(self, chat_id: str):
        return {"id": chat_id}


def _voice_event(platform: Platform) -> MessageEvent:
    return MessageEvent(
        text="voice note",
        message_type=MessageType.VOICE,
        source=SessionSource(platform=platform, chat_id="9665551234", chat_type="dm"),
        message_id="voice-1",
    )


def _hold_typing():
    async def hold(*_args, **_kwargs):
        await asyncio.Event().wait()

    return hold


async def _run(adapter: _DummyAdapter, *, tts_success: bool, reply="answer " * 300):
    adapter._keep_typing = _hold_typing()
    adapter._should_auto_tts_for_chat = lambda _chat_id: True
    adapter.play_tts = AsyncMock(
        return_value=SendResult(success=tts_success, message_id="tts-1")
    )
    adapter.set_message_handler(lambda _event: asyncio.sleep(0, result=reply))
    event = _voice_event(adapter.platform)

    def fake_tts(*, text, output_path=None):
        from pathlib import Path

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake audio")
        return json.dumps({"success": True, "file_path": output_path})

    with patch("tools.tts_tool.check_tts_requirements", return_value=True), patch(
        "tools.tts_tool.text_to_speech_tool", side_effect=fake_tts
    ):
        await adapter._process_message_background(event, build_session_key(event.source))
    return adapter


def _text_sends(adapter):
    return [s for s in adapter.sent if isinstance(s.get("content"), str) and "answer" in s["content"]]


@pytest.mark.asyncio
async def test_flag_on_audio_delivered_suppresses_text():
    adapter = _DummyAdapter()
    adapter._voice_reply_only = True
    await _run(adapter, tts_success=True)
    assert adapter.play_tts.await_count == 1
    assert not _text_sends(adapter), adapter.sent


@pytest.mark.asyncio
async def test_flag_on_tts_delivery_failed_falls_back_to_text():
    adapter = _DummyAdapter()
    adapter._voice_reply_only = True
    await _run(adapter, tts_success=False)
    assert _text_sends(adapter)


@pytest.mark.asyncio
async def test_flag_off_sends_both():
    adapter = _DummyAdapter()
    adapter._voice_reply_only = False
    await _run(adapter, tts_success=True)
    assert adapter.play_tts.await_count == 1
    assert _text_sends(adapter)
