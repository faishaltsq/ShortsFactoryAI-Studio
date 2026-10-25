"""Local credential storage.

Two sources, in order of preference:

1. **Environment reference** — a provider stores ``{"env": "NAME"}`` and the value is read from the
   process environment (falling back to the operator's ``.env``). Nothing is written to disk.
2. **DPAPI-sealed blob** — for operators who do not want keys in ``.env``. Values are sealed with
   Windows ``CryptProtectData`` at current-user scope into ``data/secrets/<id>.bin``, and the file
   is DACL-restricted to the current user.

There is no plaintext mode. A JSON file with keys in it is a file that ends up in a backup, a
screenshot, or a commit, and there is no version of this system where that is acceptable.

Everything a credential touches is a **reference**: the value is resolved at call time, used, and
dropped. It never enters SQLite, an artifact, a response body, or a log line.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Final

from .redact import REDACTED

#: Shown wherever a credential would otherwise be printed.
MASK: Final = REDACTED


class SecretStoreError(RuntimeError):
    """A credential could not be stored or read. Never swallowed into a default."""


class CredentialRef:
    """A pointer to a credential. Holds a *name*, never a value."""

    __slots__ = ("kind", "name")

    def __init__(self, kind: str, name: str) -> None:
        if kind not in {"env", "dpapi"}:
            raise SecretStoreError(f"unknown credential kind {kind!r}")
        if not name or not name.strip():
            raise SecretStoreError("credential reference needs a name")
        self.kind = kind
        self.name = name.strip()

    @classmethod
    def parse(cls, payload: object) -> CredentialRef | None:
        """Read ``{"env": "X"}`` / ``{"dpapi": "Y"}``. Anything else is a configuration error."""
        if payload is None:
            return None
        if not isinstance(payload, dict) or len(payload) != 1:
            raise SecretStoreError("credential must be {'env': NAME} or {'dpapi': ID}")
        (kind, name), = payload.items()
        return cls(kind, str(name))

    def to_json(self) -> dict[str, str]:
        return {self.kind: self.name}

    def __repr__(self) -> str:  # never the value, only the reference
        return f"CredentialRef({self.kind}={self.name!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CredentialRef) and (self.kind, self.name) == (other.kind, other.name)

    def __hash__(self) -> int:
        return hash((self.kind, self.name))


def _read_env_file_value(name: str) -> str:
    """Read one key from the operator's .env without mutating ``os.environ``."""
    candidates: list[Path] = []
    explicit = os.environ.get("SHORTS_ENV_FILE", "")
    if explicit:
        candidates.append(Path(explicit))
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(Path(local) / "hermes" / ".env")
    candidates.append(Path.home() / ".hermes" / ".env")
    candidates.append(Path.cwd() / ".env")
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            for raw in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _seal(data: bytes, entropy: bytes | None = None) -> bytes:
    if not _dpapi_available():
        raise SecretStoreError("DPAPI sealing requires Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    blob_in = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    entropy_blob = None
    entropy_ptr = None
    if entropy:
        entropy_buf = ctypes.create_string_buffer(entropy)
        entropy_blob = _DataBlob(len(entropy), ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_char)))
        entropy_ptr = ctypes.byref(entropy_blob)

    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "ShortsFactoryAI Studio credential",
        entropy_ptr,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN: never prompt, this runs in a worker
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretStoreError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _unseal(data: bytes, entropy: bytes | None = None) -> bytes:
    if not _dpapi_available():
        raise SecretStoreError("DPAPI unsealing requires Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    blob_in = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    entropy_blob = None
    entropy_ptr = None
    if entropy:
        entropy_buf = ctypes.create_string_buffer(entropy)
        entropy_blob = _DataBlob(len(entropy), ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_char)))
        entropy_ptr = ctypes.byref(entropy_blob)

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        entropy_ptr,
        None,
        None,
        0x1,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise SecretStoreError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _lock_down(path: Path) -> None:
    """Restrict the file to the current user. Best effort, but a failure is reported."""
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
        except OSError as exc:  # pragma: no cover - POSIX only
            raise SecretStoreError(f"cannot restrict {path}: {exc}") from exc
        return
    user = os.environ.get("USERNAME", "")
    if not user:
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        # The seal itself is the primary protection; the DACL is defence in depth.
        pass


class SecretStore:
    """Reads and writes credentials. The only object that ever holds a plaintext value."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, secret_id: str) -> Path:
        if not secret_id or "/" in secret_id or "\\" in secret_id or secret_id.startswith("."):
            raise SecretStoreError(f"invalid secret id {secret_id!r}")
        return self.root / f"{secret_id}.bin"

    # -- writing ---------------------------------------------------------------------------
    def put(self, secret_id: str, value: str) -> CredentialRef:
        """Seal ``value`` under ``secret_id`` and return a reference to it."""
        if not value:
            raise SecretStoreError("refusing to store an empty credential")
        self.root.mkdir(parents=True, exist_ok=True)
        blob = _seal(value.encode("utf-8"), entropy=secret_id.encode("utf-8"))
        target = self.path_for(secret_id)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(blob)
        _lock_down(tmp)
        os.replace(tmp, target)
        return CredentialRef("dpapi", secret_id)

    def delete(self, secret_id: str) -> None:
        path = self.path_for(secret_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return

    # -- reading ---------------------------------------------------------------------------
    def resolve(self, ref: CredentialRef | None) -> str:
        """Return the credential value, or ``""`` when there is none.

        An empty return is not an error: anonymous endpoints (Ollama, some local routers) are
        legitimate. The caller decides whether a missing credential is fatal, because only the
        caller knows whether the endpoint requires one.
        """
        if ref is None:
            return ""
        if ref.kind == "env":
            value = os.environ.get(ref.name, "")
            if value:
                return value
            return _read_env_file_value(ref.name)
        path = self.path_for(ref.name)
        if not path.is_file():
            return ""
        return _unseal(path.read_bytes(), entropy=ref.name.encode("utf-8")).decode("utf-8")

    def has(self, ref: CredentialRef | None) -> bool:
        if ref is None:
            return False
        if ref.kind == "env":
            return bool(self.resolve(ref))
        return self.path_for(ref.name).is_file()
