"""Assembling the transport set and the default registry.

Kept out of ``__init__`` so tests can import a transport without building a registry.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Provider
from .cli import CLIProvider
from .mock import MockProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .registry import ProviderRegistry, ProviderSpec


def build_transports() -> dict[str, Provider]:
    """One instance per transport. They hold no per-call state, so sharing is safe."""
    transports: list[Provider] = [
        OpenAICompatProvider(),
        AnthropicProvider(),
        OllamaProvider(),
        CLIProvider(),
        MockProvider(),
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
            enabled=False,
        )
    )
    return registry
