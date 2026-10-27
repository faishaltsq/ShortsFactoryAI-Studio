"""Assembling the transport set and the default registry.

Kept out of ``__init__`` so tests can import a transport without building a registry.
``SHORTS_MOCK_DELAY_MS`` (default ``"0"``) slows the mock provider so a test can observe work.
"""

from __future__ import annotations

import os

from .anthropic import AnthropicProvider
from .base import Capability, Provider
from .cli import CLIProvider
from .mock import MockProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .registry import ProviderRegistry, ProviderSpec

MOCK_DELAY_ENV = "SHORTS_MOCK_DELAY_MS"


def mock_delay_ms() -> int:
    """Read ``SHORTS_MOCK_DELAY_MS``. Invalid input is a configuration error, never a coercion.

    Digits only: ``int()`` alone would silently accept ``" 5"``, ``"+5"`` and ``"1_000"``.
    """
    raw = os.environ.get(MOCK_DELAY_ENV, "0")
    if not raw.isascii() or not raw.isdigit():
        raise ValueError(
            f"{MOCK_DELAY_ENV} must be a non-negative integer number of milliseconds, got {raw!r}"
        )
    return int(raw, 10)


def build_transports() -> dict[str, Provider]:
    """One instance per transport. They hold no per-call state, so sharing is safe.

    The delay only affects the mock transport's own latency; it does not change resolution, and
    a live job still cannot reach mock.
    """
    transports: list[Provider] = [
        OpenAICompatProvider(),
        AnthropicProvider(),
        OllamaProvider(),
        CLIProvider(),
        MockProvider(delay_ms=mock_delay_ms()),
    ]
    return {transport.transport: transport for transport in transports}


def default_registry() -> ProviderRegistry:
    """A registry that always contains a disabled-by-default mock provider.

    The mock entry exists so tests and explicit mock jobs can resolve it; it is not enabled for
    live work, and enabling it does not make a live job fall back to it.
    """
    registry = ProviderRegistry()
    registry.add(
        ProviderSpec(
            id="mock",
            label="Mock (offline)",
            transport="mock",
            model="mock-1",
            # The mock returns well-formed JSON by construction, so it genuinely provides these.
            # It does not declare vision: it cannot see, and claiming otherwise is the exact
            # failure the vision-capability rule exists to prevent.
            capabilities=[Capability.CHAT, Capability.JSON_SCHEMA],
            enabled=False,
        )
    )
    return registry
