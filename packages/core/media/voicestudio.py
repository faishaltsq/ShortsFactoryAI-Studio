"""VoiceStudio local audio adapter.

Connects to a local VoiceStudio CUDA service (OpenAI-compatible speech endpoint)
to synthesize narration audio, parse WAV PCM headers, and extract or derive
word-level alignment timestamps. Outbound requests are pinned and validated
via Netguard with `allow_private_hosts=True`.
"""

from __future__ import annotations

import io
import json
import wave
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..security.netguard import BlockedTarget, TargetPolicy, resolve_and_pin


class VoiceStudioError(RuntimeError):
    """Raised when VoiceStudio operations fail."""


@dataclass
class VoiceStudioResult:
    """Output of a successful VoiceStudio synthesis call."""

    audio_bytes: bytes
    sample_rate: int
    duration_s: float
    word_timestamps: list[dict[str, Any]] = field(default_factory=list)


class VoiceStudioAdapter:
    """Client adapter for local VoiceStudio speech synthesis service."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3900",
        timeout_s: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client = client

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        policy = TargetPolicy(allow_private_hosts=True)
        try:
            target = resolve_and_pin(url, policy)
        except BlockedTarget as exc:
            raise VoiceStudioError(f"Target blocked by netguard: {exc}") from exc

        pinned_host = f"[{target.pinned_ip}]" if ":" in target.pinned_ip and not target.pinned_ip.startswith("[") else target.pinned_ip
        pinned_url = f"{target.scheme}://{pinned_host}:{target.port}{path}"
        headers = dict(kwargs.pop("headers", None) or {})
        host_str = f"[{target.host}]" if ":" in target.host and not target.host.startswith("[") else target.host
        headers.setdefault(
            "Host",
            f"{host_str}:{target.port}" if target.port not in (80, 443) else host_str,
        )

        client = self._client or httpx.Client(
            timeout=self.timeout_s,
            follow_redirects=False,
            trust_env=False,
        )
        try:
            return client.request(method, pinned_url, headers=headers, timeout=self.timeout_s, **kwargs)
        except httpx.HTTPError as exc:
            raise VoiceStudioError(f"HTTP request failed: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

    def health(self) -> dict[str, Any]:
        """Probe service health, falling back from /health to / if 404."""
        resp = self._send("GET", "/health")
        if resp.status_code == 404:
            resp = self._send("GET", "/")

        if resp.status_code != 200:
            raise VoiceStudioError(
                f"Health check failed with status {resp.status_code}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"status": "ok", "raw": data}
        except Exception as exc:
            raise VoiceStudioError(f"Invalid JSON from health endpoint: {exc}") from exc

    def models(self) -> list[str]:
        """Query available model IDs from /v1/models."""
        resp = self._send("GET", "/v1/models")
        if resp.status_code != 200:
            raise VoiceStudioError(
                f"Models probe failed with status {resp.status_code}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise VoiceStudioError(f"Invalid JSON from models endpoint: {exc}") from exc

        if isinstance(data, list):
            return [m["id"] if isinstance(m, dict) and "id" in m else str(m) for m in data]
        if isinstance(data, dict):
            items = data.get("data") or data.get("models") or []
            if isinstance(items, list):
                return [m["id"] if isinstance(m, dict) and "id" in m else str(m) for m in items]
        return []

    def synthesize(
        self,
        text: str,
        voice: str = "alloy",
        model: str = "tts-1",
        language: str = "id",
        speed: float = 1.0,
    ) -> VoiceStudioResult:
        """Synthesize text into WAV audio with sample rate and timing metadata."""
        if not text or not text.strip():
            raise ValueError("text cannot be empty")

        payload: dict[str, Any] = {
            "model": model,
            "input": text,
            "voice": voice,
            "language": language,
            "response_format": "wav",
            "speed": speed,
        }

        resp = self._send("POST", "/v1/audio/speech", json=payload)
        if resp.status_code != 200:
            raise VoiceStudioError(
                f"Synthesis failed with status {resp.status_code}: {resp.text[:500]}"
            )

        audio_bytes = resp.content
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                sample_rate = wf.getframerate()
                frames = wf.getnframes()
                if sample_rate <= 0 or frames <= 0:
                    raise VoiceStudioError(
                        f"WAV audio is empty or zero-duration: {sample_rate=} {frames=}"
                    )
                duration_s = frames / float(sample_rate)
        except Exception as exc:
            if isinstance(exc, VoiceStudioError):
                raise
            raise VoiceStudioError(f"Failed to parse WAV audio: {exc}") from exc

        word_timestamps: list[dict[str, Any]] = []
        raw_header = resp.headers.get("x-word-timestamps")
        if raw_header:
            try:
                parsed = json.loads(raw_header)
                if isinstance(parsed, list):
                    valid_items: list[dict[str, Any]] = []
                    for item in parsed:
                        if isinstance(item, dict) and "word" in item:
                            w = str(item["word"]).strip()
                            s_ms = int(item.get("startMs", int(float(item.get("start", 0)) * 1000)))
                            e_ms = int(item.get("endMs", int(float(item.get("end", 0)) * 1000)))
                            if w and s_ms >= 0 and e_ms > s_ms:
                                valid_items.append({"word": w, "startMs": s_ms, "endMs": e_ms})
                    if valid_items and len(valid_items) == len(parsed):
                        word_timestamps = valid_items
            except Exception:
                word_timestamps = []

        if not word_timestamps:
            words = text.split()
            if words:
                total_ms = max(1, int(duration_s * 1000))
                total_chars = sum(len(w) for w in words)
                current_ms = 0
                for i, w in enumerate(words):
                    if i == len(words) - 1:
                        next_ms = total_ms
                    else:
                        weight = len(w) / total_chars if total_chars > 0 else 1.0 / len(words)
                        w_dur = int(total_ms * weight)
                        next_ms = min(total_ms, current_ms + max(1, w_dur))
                    if next_ms <= current_ms:
                        next_ms = current_ms + 1
                    word_timestamps.append(
                        {
                            "word": w,
                            "startMs": current_ms,
                            "endMs": next_ms,
                        }
                    )
                    current_ms = next_ms

        return VoiceStudioResult(
            audio_bytes=audio_bytes,
            sample_rate=sample_rate,
            duration_s=duration_s,
            word_timestamps=word_timestamps,
        )
