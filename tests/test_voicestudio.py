from __future__ import annotations

import io
import unittest.mock as mock
import wave

import httpx
import pytest

from packages.core.media.voicestudio import (
    VoiceStudioAdapter,
    VoiceStudioError,
    VoiceStudioResult,
)
from packages.core.security.netguard import BlockedTarget, TargetPolicy


def _make_wav_bytes(sample_rate: int = 24000, duration_s: float = 1.0) -> bytes:
    """Generate in-memory valid PCM WAV audio bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = int(sample_rate * duration_s)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def test_voicestudio_health_check_success() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    mock_resp = httpx.Response(200, json={"status": "ok", "device": "cuda:0", "version": "0.5.7"})
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp):
        health = adapter.health()
        assert health["status"] == "ok"
        assert "cuda" in health["device"]


def test_voicestudio_health_check_fallback_to_root() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    resp_404 = httpx.Response(404, text="Not Found")
    resp_200 = httpx.Response(200, json={"status": "ok", "device": "cuda:0"})

    with mock.patch.object(httpx.Client, "request", side_effect=[resp_404, resp_200]) as mock_req:
        health = adapter.health()
        assert health["status"] == "ok"
        assert mock_req.call_count == 2


def test_voicestudio_health_check_failure_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    resp_500 = httpx.Response(500, text="Internal Server Error")
    with mock.patch.object(httpx.Client, "request", return_value=resp_500):
        with pytest.raises(VoiceStudioError, match="status 500"):
            adapter.health()


def test_voicestudio_health_check_network_error_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with mock.patch.object(httpx.Client, "request", side_effect=httpx.ConnectError("Failed")):
        with pytest.raises(VoiceStudioError, match="HTTP request failed"):
            adapter.health()


def test_voicestudio_models_probe_success() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    mock_resp = httpx.Response(200, json={"data": [{"id": "tts-1"}, {"id": "tts-1-hd"}]})
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp):
        models = adapter.models()
        assert models == ["tts-1", "tts-1-hd"]


def test_voicestudio_models_probe_failure_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    resp_500 = httpx.Response(500, text="Internal Server Error")
    with mock.patch.object(httpx.Client, "request", return_value=resp_500):
        with pytest.raises(VoiceStudioError, match="status 500"):
            adapter.models()


def test_voicestudio_synthesis_success_with_derived_timestamps() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    wav_bytes = _make_wav_bytes(sample_rate=24000, duration_s=1.5)
    mock_resp = httpx.Response(200, content=wav_bytes, headers={"Content-Type": "audio/wav"})

    with mock.patch.object(httpx.Client, "request", return_value=mock_resp) as mock_req:
        res = adapter.synthesize("Halo dunia", voice="alloy", model="tts-1", language="id", speed=1.1)
        assert isinstance(res, VoiceStudioResult)
        assert res.audio_bytes == wav_bytes
        assert res.sample_rate == 24000
        assert pytest.approx(res.duration_s, rel=1e-2) == 1.5
        assert len(res.word_timestamps) == 2
        assert res.word_timestamps[0]["word"] == "Halo"
        assert res.word_timestamps[1]["word"] == "dunia"
        assert res.word_timestamps[0]["startMs"] < res.word_timestamps[0]["endMs"]
        assert res.word_timestamps[1]["endMs"] == 1500
        # Assert payload contains language and speed
        req_kwargs = mock_req.call_args[1]
        assert req_kwargs["json"]["language"] == "id"
        assert req_kwargs["json"]["speed"] == 1.1


def test_voicestudio_synthesis_zero_frames_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    zero_wav = _make_wav_bytes(sample_rate=24000, duration_s=0.0)
    mock_resp = httpx.Response(200, content=zero_wav)
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp):
        with pytest.raises(VoiceStudioError, match="zero-duration"):
            adapter.synthesize("Halo")


def test_voicestudio_synthesis_malformed_header_timestamps_falls_back_to_proportional() -> None:
    from packages.core.contracts.scene import WordTimestamp

    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    wav_bytes = _make_wav_bytes(sample_rate=24000, duration_s=1.0)

    # 1. Non-object list
    mock_resp1 = httpx.Response(
        200,
        content=wav_bytes,
        headers={"x-word-timestamps": '["not", "a", "valid", "object", "list"]'},
    )
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp1):
        res1 = adapter.synthesize("Halo dunia")
        assert len(res1.word_timestamps) == 2
        assert res1.word_timestamps[0]["word"] == "Halo"
        assert res1.word_timestamps[1]["word"] == "dunia"
        for wt in res1.word_timestamps:
            assert WordTimestamp.model_validate(wt)

    # 2. Inverted/zero-duration timestamps (startMs >= endMs)
    mock_resp2 = httpx.Response(
        200,
        content=wav_bytes,
        headers={"x-word-timestamps": '[{"word": "Halo", "startMs": 500, "endMs": 100}]'},
    )
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp2):
        res2 = adapter.synthesize("Halo dunia")
        assert len(res2.word_timestamps) == 2
        assert res2.word_timestamps[0]["word"] == "Halo"
        assert res2.word_timestamps[1]["word"] == "dunia"
        for wt in res2.word_timestamps:
            assert WordTimestamp.model_validate(wt)


def test_voicestudio_custom_client_injection() -> None:
    custom_client = httpx.Client()
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900", client=custom_client)
    mock_resp = httpx.Response(200, json={"status": "ok"})
    with mock.patch.object(custom_client, "request", return_value=mock_resp) as mock_req:
        res = adapter.health()
        assert res["status"] == "ok"
        assert mock_req.called


def test_voicestudio_invalid_json_responses() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    bad_resp = httpx.Response(200, text="not json content")
    with mock.patch.object(httpx.Client, "request", return_value=bad_resp):
        with pytest.raises(VoiceStudioError, match="Invalid JSON"):
            adapter.health()
        with pytest.raises(VoiceStudioError, match="Invalid JSON"):
            adapter.models()


def test_voicestudio_synthesis_with_header_timestamps() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    wav_bytes = _make_wav_bytes(sample_rate=16000, duration_s=1.0)
    mock_resp = httpx.Response(
        200,
        content=wav_bytes,
        headers={
            "Content-Type": "audio/wav",
            "x-word-timestamps": '[{"word": "Halo", "startMs": 0, "endMs": 400}, {"word": "dunia", "startMs": 450, "endMs": 950}]',
        },
    )

    with mock.patch.object(httpx.Client, "request", return_value=mock_resp):
        res = adapter.synthesize("Halo dunia")
        assert len(res.word_timestamps) == 2
        assert res.word_timestamps[0]["word"] == "Halo"
        assert res.word_timestamps[0]["startMs"] == 0
        assert res.word_timestamps[0]["endMs"] == 400
        assert res.word_timestamps[1]["word"] == "dunia"
        assert res.word_timestamps[1]["endMs"] == 950


def test_voicestudio_synthesis_rejects_empty_text() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with pytest.raises(ValueError, match="empty"):
        adapter.synthesize("   ")


def test_voicestudio_synthesis_500_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    resp_500 = httpx.Response(500, text="Synthesis crash")
    with mock.patch.object(httpx.Client, "request", return_value=resp_500):
        with pytest.raises(VoiceStudioError, match="status 500"):
            adapter.synthesize("Halo")


def test_voicestudio_synthesis_network_error_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with mock.patch.object(httpx.Client, "request", side_effect=httpx.ReadTimeout("Timeout")):
        with pytest.raises(VoiceStudioError, match="HTTP request failed"):
            adapter.synthesize("Halo")


def test_voicestudio_synthesis_corrupt_wav_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    mock_resp = httpx.Response(200, content=b"invalid-wav-data")
    with mock.patch.object(httpx.Client, "request", return_value=mock_resp):
        with pytest.raises(VoiceStudioError, match="WAV"):
            adapter.synthesize("Halo")


def test_voicestudio_netguard_integration() -> None:
    from packages.core.security.netguard import OutboundPolicy

    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    mock_resp = httpx.Response(200, json={"status": "ok", "device": "cuda"})

    fake_policy = OutboundPolicy(
        url="http://127.0.0.1:3900/health",
        scheme="http",
        host="127.0.0.1",
        port=3900,
        pinned_ip="127.0.0.1",
        addresses=("127.0.0.1",),
    )

    with mock.patch("packages.core.media.voicestudio.resolve_and_pin", return_value=fake_policy) as mock_pin:
        with mock.patch.object(httpx.Client, "request", return_value=mock_resp) as mock_req:
            adapter.health()
            assert mock_pin.called
            args, kwargs = mock_pin.call_args
            policy = kwargs.get("policy") or (args[1] if len(args) > 1 else None)
            assert isinstance(policy, TargetPolicy)
            assert policy.allow_private_hosts is True
            # Verify request was sent to pinned IP and with Host header
            call_args, call_kwargs = mock_req.call_args
            assert call_args[0] == "GET"
            assert call_args[1] == "http://127.0.0.1:3900/health"
            assert call_kwargs["headers"]["Host"] == "127.0.0.1:3900"


def test_voicestudio_netguard_blocked_target_raises_voicestudio_error() -> None:
    adapter = VoiceStudioAdapter(base_url="http://127.0.0.1:3900")
    with mock.patch(
        "packages.core.media.voicestudio.resolve_and_pin",
        side_effect=BlockedTarget("http://127.0.0.1:3900/health", "blocked"),
    ):
        with pytest.raises(VoiceStudioError, match="blocked"):
            adapter.health()
