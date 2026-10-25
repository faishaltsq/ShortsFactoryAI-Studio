"""Model access. Nothing outside this package may talk to a model endpoint.

The shape that matters: configuration is data, resolution is pure, and a call carries its own
parameters. No provider object is ever mutated to apply an agent's settings — that was the donor's
bug, where the second agent on a shared provider silently ran the first agent's model.
"""

from .base import (
    Capability,
    CapabilityMismatch,
    Health,
    NoProviderAvailable,
    ProviderError,
    ProviderResult,
    ResolvedCall,
    Usage,
)
from .registry import ProviderRegistry, ProviderSpec
from .resolve import Binding, resolve_call
from .usage import UsageTracker

__all__ = [
    "Binding",
    "Capability",
    "CapabilityMismatch",
    "Health",
    "NoProviderAvailable",
    "ProviderError",
    "ProviderRegistry",
    "ProviderResult",
    "ProviderSpec",
    "ResolvedCall",
    "Usage",
    "UsageTracker",
    "resolve_call",
]
