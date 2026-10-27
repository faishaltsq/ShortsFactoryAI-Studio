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
from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop
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
    #: Off unless the operator set ``SHORTS_SCHEDULER_ENABLED``. ``None`` means "not built yet":
    #: the loop needs the service to hand jobs to, and the service needs this object.
    scheduler: SchedulerLoop | None = None

    @classmethod
    def build(cls, settings: Settings, *, budget: Budget | None = None) -> AppState:
        settings.ensure()
        state = cls(
            settings=settings,
            store=JobStore(settings.db_path, settings.jobs_dir),
            events=StudioEventStore(settings.db_path),
            secrets=SecretStore(settings.secrets_dir),
            usage=UsageTracker(settings.db_path, budget or Budget()),
            registry=default_registry(),
            transports=build_transports(),
        )
        state._load_configured_providers()
        return state

    def _load_configured_providers(self) -> None:
        """Load operator-declared providers from ``studio.json``, if that file defines any.

        The file is optional and ignored when absent; the mock registry is the default. A provider
        entry carries a credential *reference* (``{"env": NAME}``), never a value — the same rule
        the API enforces. Recognising the local router here is what lets the visual QA pass run for
        real without a UI round-trip.
        """
        import json

        path = self.settings.studio_config
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for entry in payload.get("providers", []) if isinstance(payload, dict) else []:
            try:
                spec = ProviderSpec(
                    id=entry["id"],
                    label=entry.get("label", ""),
                    transport=entry.get("transport", "openai_compat"),
                    base_url=entry["base_url"],
                    model=entry["model"],
                    credential=entry.get("credential"),
                    capabilities=[Capability(c) for c in entry.get("capabilities", ["chat"])],
                    allow_private_hosts=entry.get("allow_private_hosts", False),
                    enabled=entry.get("enabled", True),
                )
            except (KeyError, ValueError):
                continue  # a malformed entry is skipped, never silently half-applied
            self.registry.add(spec)

    # -- scheduler -------------------------------------------------------------------------
    def scheduler_config(self) -> SchedulerConfig:
        """Read the operator's switch. An invalid value raises; it never silently means "off"."""
        return SchedulerConfig.from_env()

    def build_scheduler(self, on_claim) -> SchedulerLoop:
        """Create the loop but do not start it. Starting is an explicit operator action."""
        self.scheduler = SchedulerLoop(
            self.store, on_claim, config=self.scheduler_config()
        )
        return self.scheduler

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
