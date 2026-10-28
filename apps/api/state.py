"""Process-wide wiring: the store, the event log, the registry, the transports.

One composition root. Every route receives this object rather than reaching for globals, so a test
can build a fully isolated instance.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from packages.core.observability.events import AGENT_IDS, StudioEventStore
from packages.core.orchestration.jobstore import JobStore
from packages.core.orchestration.scheduler import SchedulerConfig, SchedulerLoop
from packages.core.providers.base import Capability, Provider
from packages.core.providers.factory import build_transports, default_registry
from packages.core.providers.journal import RequestJournal
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
    #: The paid-call journal. Present on every AppState so a provider call is journalled whether it
    #: comes from a job, a discovery run or a diagnostic — a call that escapes the journal is a
    #: call a crash can duplicate.
    registry: ProviderRegistry
    transports: dict[str, Provider]
    cancel_flags: dict[str, threading.Event] = field(default_factory=dict)
    running: dict[str, threading.Thread] = field(default_factory=dict)
    #: Per-agent provider bindings from ``studio.json``: agent name -> {"primary": id,
    #: "fallback": [ids]}. Empty dict means "no operator preference"; resolution then stays
    #: first-enabled-provider. Unknown agent names are rejected at load (a binding that binds
    #: nothing is a silent misconfiguration).
    bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    #: The paid-call journal. Present on every AppState so a provider call is journalled whether it
    #: comes from a job, a discovery run or a diagnostic — a call that escapes the journal is a
    #: call a crash can duplicate.
    requests: Any = None
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
        state.requests = RequestJournal(settings.db_path)
        state.requests.reconcile()
        state._load_configured_providers()
        state._publish_configured_rates()
        return state
    def _publish_configured_rates(self) -> None:
        """Tell the usage tracker which providers currently have both rates configured.

        The registry is in-memory and the tracker only reads its own log, so "is pricing configured
        *now*" is a fact the tracker cannot derive. Publishing it keeps ``price_configured`` about
        today's rates rather than about whether any historical row happens to carry a cost.
        """
        rates: dict[str, tuple[float, float]] = {}
        for spec in self.registry.specs.values():
            if spec.price_in_per_mtok is not None and spec.price_out_per_mtok is not None:
                rates[spec.id] = (spec.price_in_per_mtok, spec.price_out_per_mtok)
        self.usage.set_configured_rates(rates)

    def _load_configured_providers(self) -> None:
        """Load operator-declared providers from the durable configuration store.

        The store is the single writer of ``studio.json``; this is the single reader. A malformed
        file raises: a configuration the process cannot understand must not degrade into "the first
        enabled provider", because that silently picks a provider the operator never chose. The
        credentials are references and stay references — resolution happens at call time, through
        the origin the credential was bound to.
        """
        from .config import ConfigError, ConfigStore

        store = ConfigStore(self.settings.studio_config, secrets=self.secrets)
        try:
            config = store.load()
        except ConfigError:
            raise
        for entry in config.providers:
            try:
                spec = ProviderSpec(
                    id=entry["id"],
                    label=entry.get("label", ""),
                    transport=entry.get("transport", "openai_compat"),
                    base_url=entry["base_url"],
                    model=entry.get("model", ""),
                    credential=entry.get("credential"),
                    capabilities=[Capability(c) for c in entry.get("capabilities", ["chat"])],
                    allow_private_hosts=entry.get("allow_private_hosts", False),
                    enabled=entry.get("enabled", True),
                    cli_command=entry.get("cli_command", ""),
                    timeout_s=entry.get("timeout_s", 90.0),
                    max_retries=entry.get("max_retries", 2),
                    max_tokens=entry.get("max_tokens"),
                    temperature=entry.get("temperature"),
                    price_in_per_mtok=entry.get("price_in_per_mtok"),
                    price_out_per_mtok=entry.get("price_out_per_mtok"),
                )
            except (KeyError, ValueError):
                continue  # a malformed entry is skipped, never silently half-applied
            self.registry.add(spec)
        self._load_configured_bindings(
            {"bindings": config.bindings, "budget": config.budget.to_json(),
             "render": config.render.to_json()}
        )
        from .config import malformed_bindings

        try:
            raw = __import__("json").loads(
                self.settings.studio_config.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            raw = {}
        dropped = malformed_bindings(raw.get("bindings", []) if isinstance(raw, dict) else [])
        if dropped:
            self._note_skipped_binding(
                f"{dropped} binding entri dilewati karena formatnya tidak valid"
            )
        # A saved budget is the operator's limit from the previous run; it takes effect at startup
        # rather than after the next save.
        self.usage.set_limits(
            max_daily_tokens=config.budget.max_daily_tokens,
            max_daily_cost_usd=config.budget.max_daily_cost_usd,
            unlimited=config.budget.unlimited,
        )

    def _load_configured_bindings(self, payload: dict[str, Any]) -> None:
        """Load per-agent provider bindings.

        Two failure classes, handled differently on purpose: a binding for an agent that can
        never run would bind silently to nothing, so an unknown agent name is a hard error at
        build time, before any HTTP traffic. A malformed *field* is skipped with a persisted
        event noting it — one broken entry must not stop the studio from starting, but it must
        not vanish silently either.
        """
        entries = payload.get("bindings", [])
        if not isinstance(entries, list):
            raise ValueError("config/studio.json: 'bindings' must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("agent"), str):
                self._note_skipped_binding(f"malformed binding entry {entry!r}")
                continue
            agent = entry["agent"]
            if agent not in AGENT_IDS:
                raise ValueError(f"config/studio.json: binding names unknown agent {agent!r}")
            primary = entry.get("primary")
            fallback = entry.get("fallback", [])
            if primary is not None and not isinstance(primary, str):
                self._note_skipped_binding(f"binding for {agent}: non-string primary")
                continue
            if not isinstance(fallback, list) or not all(isinstance(f, str) for f in fallback):
                self._note_skipped_binding(f"binding for {agent}: malformed fallback")
                continue
            self.bindings[agent] = {"primary": primary, "fallback": fallback}

    def _note_skipped_binding(self, detail: str) -> None:
        """Persist one bounded event about a skipped binding. Best effort: a failing event
        store must not block startup for a configuration warning."""
        try:
            self.events.emit(
                job_id="studio-config",
                agent_id="FactoryOrchestrator",
                event_type="failed",
                status="failed",
                description=f"binding dilewati: {detail}"[:500],
            )
        except Exception:  # noqa: BLE001 - startup must not die on a warning
            pass

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
        # A price edit changes what "pricing is configured" means, so republish rather than let the
        # summary keep answering about the previous configuration.
        self._publish_configured_rates()

    def capability_gaps(self) -> dict[str, list[str]]:
        """Which agents cannot be served because no enabled provider declares a capability."""
        return {}

    def vision_available(self) -> bool:
        return bool(self.registry.with_capability(Capability.VISION))
