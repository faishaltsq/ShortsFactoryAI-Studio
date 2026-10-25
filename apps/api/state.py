"""Process-wide wiring: the store, the event log, the registry, the transports.

One composition root. Every route receives this object rather than reaching for globals, so a test
can build a fully isolated instance.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from packages.core.observability.events import StudioEventStore
from packages.core.orchestration.jobstore import JobStore
from packages.core.providers.base import Capability, Provider
from packages.core.providers.factory import build_transports, default_registry
from packages.core.providers.registry import ProviderRegistry, ProviderSpec
from packages.core.providers.usage import Budget, UsageTracker
from packages.core.security.secretstore import SecretStore

from .settings import Settings


@dataclass
class AppState:
    settings: Settings
    store: JobStore
    events: StudioEventStore
    secrets: SecretStore
    usage: UsageTracker
    registry: ProviderRegistry
    transports: dict[str, Provider]
    cancel_flags: dict[str, threading.Event] = field(default_factory=dict)
    running: dict[str, threading.Thread] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def build(cls, settings: Settings, *, budget: Budget | None = None) -> AppState:
        settings.ensure()
        return cls(
            settings=settings,
            store=JobStore(settings.db_path, settings.jobs_dir),
            events=StudioEventStore(settings.db_path),
            secrets=SecretStore(settings.secrets_dir),
            usage=UsageTracker(settings.db_path, budget or Budget()),
            registry=default_registry(),
            transports=build_transports(),
        )

    # -- cancellation ----------------------------------------------------------------------
    def cancel_flag(self, job_id: str) -> threading.Event:
        with self.lock:
            return self.cancel_flags.setdefault(job_id, threading.Event())

    def request_cancel(self, job_id: str) -> None:
        self.cancel_flag(job_id).set()

    def clear_cancel(self, job_id: str) -> None:
        with self.lock:
            self.cancel_flags.pop(job_id, None)

    # -- providers -------------------------------------------------------------------------
    def provider_specs(self) -> list[dict[str, Any]]:
        return self.registry.public_view()

    def upsert_provider(self, spec: ProviderSpec) -> None:
        self.registry.add(spec)

    def capability_gaps(self) -> dict[str, list[str]]:
        """Which agents cannot be served because no enabled provider declares a capability."""
        return {}

    def vision_available(self) -> bool:
        return bool(self.registry.with_capability(Capability.VISION))
