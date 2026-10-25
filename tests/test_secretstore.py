"""Credential handling. No value may appear in a repr, an error, or a response shape."""

from __future__ import annotations

import sys

import pytest

from packages.core.security.secretstore import (
    CredentialRef,
    SecretStore,
    SecretStoreError,
    _read_env_file_value,
)


def test_reference_never_holds_a_value():
    ref = CredentialRef("env", "MY_KEY")
    assert "MY_KEY" in repr(ref)
    assert ref.to_json() == {"env": "MY_KEY"}


def test_parse_accepts_both_shapes():
    assert CredentialRef.parse({"env": "A"}) == CredentialRef("env", "A")
    assert CredentialRef.parse({"dpapi": "b"}) == CredentialRef("dpapi", "b")
    assert CredentialRef.parse(None) is None


@pytest.mark.parametrize(
    "payload",
    [{"env": "A", "dpapi": "B"}, {}, {"file": "x"}, "plainstring"],
)
def test_parse_refuses_ambiguous_or_unknown_shapes(payload):
    with pytest.raises(SecretStoreError):
        CredentialRef.parse(payload)


def test_unknown_kind_is_refused():
    with pytest.raises(SecretStoreError):
        CredentialRef("plaintext", "x")


def test_secret_id_cannot_escape_the_directory(tmp_path):
    store = SecretStore(tmp_path)
    for bad in ("../escape", "a/b", "a\\b", ".hidden", ""):
        with pytest.raises(SecretStoreError):
            store.path_for(bad)


def test_env_reference_reads_the_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SF_TEST_KEY", "value-from-env")
    store = SecretStore(tmp_path)
    assert store.resolve(CredentialRef("env", "SF_TEST_KEY")) == "value-from-env"
    assert store.has(CredentialRef("env", "SF_TEST_KEY")) is True


def test_missing_env_reference_resolves_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("SF_ABSENT_KEY", raising=False)
    monkeypatch.setenv("SHORTS_ENV_FILE", str(tmp_path / "nope.env"))
    store = SecretStore(tmp_path)
    assert store.resolve(CredentialRef("env", "SF_ABSENT_KEY")) == ""
    assert store.has(CredentialRef("env", "SF_ABSENT_KEY")) is False


def test_env_file_fallback(monkeypatch, tmp_path):
    env_file = tmp_path / "operator.env"
    env_file.write_text('SF_FROM_FILE="quoted-value"\n', encoding="utf-8")
    monkeypatch.delenv("SF_FROM_FILE", raising=False)
    monkeypatch.setenv("SHORTS_ENV_FILE", str(env_file))
    assert _read_env_file_value("SF_FROM_FILE") == "quoted-value"


def test_no_reference_resolves_empty(tmp_path):
    store = SecretStore(tmp_path)
    assert store.resolve(None) == ""
    assert store.has(None) is False


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_round_trip_never_writes_plaintext(tmp_path):
    store = SecretStore(tmp_path)
    value = "sk-" + "roundtrip" + "-value-123456"
    ref = store.put("worker", value)
    assert ref == CredentialRef("dpapi", "worker")
    blob = (tmp_path / "worker.bin").read_bytes()
    assert value.encode() not in blob, "the sealed file must not contain the plaintext"
    assert store.resolve(ref) == value
    store.delete("worker")
    assert store.resolve(ref) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_blob_is_bound_to_its_id(tmp_path):
    """Entropy is the secret id, so a renamed blob does not decrypt."""
    store = SecretStore(tmp_path)
    store.put("one", "value-one-123456")
    (tmp_path / "one.bin").rename(tmp_path / "two.bin")
    with pytest.raises(SecretStoreError):
        store.resolve(CredentialRef("dpapi", "two"))


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_empty_credential_is_refused(tmp_path):
    with pytest.raises(SecretStoreError):
        SecretStore(tmp_path).put("x", "")
