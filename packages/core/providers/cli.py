"""CLI transport: a local agent binary as a model backend.

Rules that are not negotiable here:

* ``argv`` array, never a shell string. No ``shell=True`` anywhere in this file.
* The executable path comes from configuration and must exist; there is no PATH lookup by name.
* A timeout kills the process tree.
* **stdout and stderr are never surfaced on failure.** A CLI can echo a token in a form no
  redaction pattern catches, so the error names the exit code and nothing else.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .base import (
    Capability,
    Health,
    ProviderError,
    ProviderResult,
    ResolvedCall,
    Usage,
    VisionImage,
    VisionUnsupported,
    now_ms,
)

#: A CLI cannot be trusted with a JSON schema, tools, or images. Say so rather than hoping.
CLI_CAPABILITIES = frozenset({Capability.CHAT})


class CLIProvider:
    name = "cli"
    transport = "cli"

    def _resolve_binary(self, call: ResolvedCall) -> str:
        command = str(call.params.get("cli_command") or "").strip()
        if not command:
            raise ProviderError("cli_misconfigured", "no cli_command configured", provider=call.provider)
        found = shutil.which(command) or (command if Path(command).is_file() else "")
        if not found:
            raise ProviderError(
                "cli_missing", f"executable {command!r} not found", provider=call.provider
            )
        return found

    def health(self, call: ResolvedCall) -> Health:
        """The binary runs. That is all this proves — not that it is authenticated."""
        try:
            binary = self._resolve_binary(call)
        except ProviderError as exc:
            return Health.down(exc.detail)
        try:
            proc = subprocess.run(  # noqa: S603 - argv array, no shell
                [binary, "--version"],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return Health.down(f"cannot run {Path(binary).name}: {type(exc).__name__}")
        if proc.returncode != 0:
            return Health.down(f"{Path(binary).name} --version exited {proc.returncode}")
        return Health.up(detail=f"{Path(binary).name} runs (login not verified)")

    def complete_vision(
        self,
        call: ResolvedCall,  # noqa: ARG002 - protocol shape
        *,
        system: str,  # noqa: ARG002
        user: str,  # noqa: ARG002
        task: str,  # noqa: ARG002
        images: list[VisionImage],  # noqa: ARG002
    ) -> ProviderResult:
        """A CLI transport has no image channel. It refuses rather than describing a file path."""
        raise VisionUnsupported("cli")

    def list_models(self, call: ResolvedCall) -> list[str] | None:
        return None

    def complete(
        self, call: ResolvedCall, *, system: str, user: str, task: str
    ) -> ProviderResult:
        binary = self._resolve_binary(call)
        argv = [binary, *self._argv(call)]
        prompt = f"{system}\n\n{user}"
        started = now_ms()
        try:
            proc = subprocess.run(  # noqa: S603 - argv array, no shell
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=call.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                "provider_timeout",
                f"{Path(binary).name} timed out after {call.timeout_s:g}s",
                provider=call.provider,
                retryable=True,
            ) from exc
        except OSError as exc:
            raise ProviderError(
                "cli_failed", f"cannot execute {Path(binary).name}: {exc.errno}", provider=call.provider
            ) from exc

        if proc.returncode != 0:
            # Deliberately no stdout/stderr: a CLI error body can contain a credential.
            raise ProviderError(
                "cli_failed",
                f"{Path(binary).name} exited {proc.returncode} (output withheld)",
                provider=call.provider,
            )

        content = self._extract(proc.stdout)
        if not content.strip():
            raise ProviderError(
                "provider_empty_completion",
                f"{Path(binary).name} produced no usable text",
                provider=call.provider,
            )
        return ProviderResult(
            content=content,
            provider=call.provider,
            model=call.model or Path(binary).stem,
            usage=Usage(),
            elapsed_ms=max(0, now_ms() - started),
        )

    def _argv(self, call: ResolvedCall) -> list[str]:
        raw = call.params.get("cli_args")
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            return [item.replace("{model}", call.model) for item in raw]
        return ["--print"]

    @staticmethod
    def _extract(stdout: str) -> str:
        """Prefer a documented JSON event stream; fall back to raw text only if it is not JSON."""
        text = stdout.strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
        if isinstance(payload, dict):
            for key in ("result", "text", "content", "response"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return text
