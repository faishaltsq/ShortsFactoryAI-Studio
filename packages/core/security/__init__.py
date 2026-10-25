"""Outbound network policy, credential sealing, and redaction.

Every outbound request that is not a fixed vendor endpoint goes through :mod:`netguard`.
"""

from .netguard import (
    BlockedTarget,
    OutboundPolicy,
    TargetPolicy,
    check_target,
    resolve_and_pin,
)
from .redact import REDACTED, redact, redact_url

__all__ = [
    "REDACTED",
    "BlockedTarget",
    "OutboundPolicy",
    "TargetPolicy",
    "check_target",
    "redact",
    "redact_url",
    "resolve_and_pin",
]
