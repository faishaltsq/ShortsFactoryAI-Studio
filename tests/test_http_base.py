"""The transport capabilities a real OAuth exchange and resumable upload need.

Every test here runs against a loopback ``StubServer``. No network, no credential, no vendor SDK.
The point is that the *plumbing* is proven before any real endpoint exists — and that the two
properties ADR-005 depends on (resolve-then-pin, no redirects) still hold for the new code paths.

RED order matters in this file: each test names the failure it prevents.
"""

from __future__ import annotations

import pytest

from packages.core.providers.base import ProviderError
from packages.core.providers.http_base import PinnedHTTP, ResumeInfo, UploadBody
from tests.stub_server import StubServer


def _origin(stub: StubServer) -> str:
    """The stub's origin without its ``/v1`` suffix, so paths are the paths we register."""
    return f"http://127.0.0.1:{stub.port}"


def _http() -> PinnedHTTP:
    # Zero retries: a test that retries a 500 three times is a slow test that hides the status.
    return PinnedHTTP(timeout_s=5.0, max_retries=0)


# -- form bodies ---------------------------------------------------------------------------------


def test_a_form_body_is_url_encoded_with_the_right_content_type():
    """An OAuth code exchange is a form POST. ``json=`` cannot express it."""
    with StubServer() as stub:
        stub.route("POST", "/token", body={"access_token": "at"})
        _http().request(
            "POST",
            f"{_origin(stub)}/token",
            data={"grant_type": "authorization_code", "code": "abc", "redirect_uri": "http://127.0.0.1:9/cb"},
            allow_private_hosts=True,
        )
        recorded = stub.recorded[-1]
        assert recorded.headers["content-type"] == "application/x-www-form-urlencoded"
        assert recorded.raw == (
            b"grant_type=authorization_code&code=abc&redirect_uri=http%3A%2F%2F127.0.0.1%3A9%2Fcb"
        )


def test_form_values_are_percent_encoded_not_raw():
    with StubServer() as stub:
        stub.route("POST", "/token", body={})
        _http().request(
            "POST",
            f"{_origin(stub)}/token",
            data={"scope": "a b", "code": "x&y=z"},
            allow_private_hosts=True,
        )
        raw = stub.recorded[-1].raw
        assert b"scope=a+b" in raw or b"scope=a%20b" in raw
        assert b"code=x%26y%3Dz" in raw


def test_json_and_data_together_are_refused():
    """Two body encodings on one request is a bug in the caller, not something to guess about."""
    with StubServer() as stub:
        stub.route("POST", "/token", body={})
        with pytest.raises(ValueError, match="json.*data|data.*json"):
            _http().request(
                "POST",
                f"{_origin(stub)}/token",
                json={"a": 1},
                data={"b": "2"},
                allow_private_hosts=True,
            )
        assert stub.recorded == [], "the request must not be sent at all"


def test_a_form_body_still_goes_through_the_netguard_pin():
    """The new path must not be a way around the policy. A denied host stays denied."""
    with pytest.raises(ProviderError) as exc:
        _http().request("POST", "http://169.254.169.254/token", data={"a": "b"})
    assert exc.value.code == "target_blocked"
    assert "169.254.169.254" in exc.value.detail


def test_a_form_body_still_refuses_a_redirect():
    with StubServer() as stub:
        stub.route("POST", "/token", status=302, body={}, headers={"location": "http://evil.example/x"})
        with pytest.raises(ProviderError) as exc:
            _http().request(
                "POST", f"{_origin(stub)}/token", data={"a": "b"}, allow_private_hosts=True
            )
        assert exc.value.code == "provider_redirect"
        assert "evil.example" in exc.value.detail


# -- upload bodies -------------------------------------------------------------------------------


def test_an_upload_body_streams_the_file_in_chunks(tmp_path):
    payload = bytes(range(256)) * 40  # 10240 bytes
    path = tmp_path / "video.mp4"
    path.write_bytes(payload)

    body = UploadBody.from_path(path, content_type="video/mp4")
    assert body.content_length == len(payload)
    assert body.content_type == "video/mp4"
    assert body.size == len(payload)

    # Chunk size is a property of the body, so a test can force several chunks over a small file
    # and assert the concatenation is exact — the property that matters for a multi-GB video.
    small = UploadBody.from_path(path, content_type="video/mp4", chunk_bytes=1024)
    chunks = list(small.chunks())
    assert len(chunks) == 10, f"10240 bytes at 1024 per chunk is 10 chunks, got {len(chunks)}"
    assert b"".join(chunks) == payload, "the byte count and the bytes must be exact"
    assert all(len(chunk) <= 1024 for chunk in chunks)


def test_an_upload_body_declares_the_file_size_and_refuses_a_mismatch(tmp_path):
    """A declared length that disagrees with the file is how a truncated upload looks normal."""
    path = tmp_path / "video.mp4"
    path.write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="content_length"):
        UploadBody.from_path(path, content_length=99)


def test_an_upload_body_refuses_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        UploadBody.from_path(tmp_path / "absent.mp4")


def test_an_upload_body_reaches_the_server_byte_for_byte(tmp_path):
    payload = b"\x00\x01\x02binary-payload" * 500
    path = tmp_path / "video.mp4"
    path.write_bytes(payload)

    with StubServer() as stub:
        stub.route("POST", "/upload", body={"ok": True})
        response = _http().request(
            "POST",
            f"{_origin(stub)}/upload",
            body=UploadBody.from_path(path, content_type="video/mp4"),
            allow_private_hosts=True,
        )
        assert response.status_code == 200
        recorded = stub.recorded[-1]
        assert recorded.raw == payload
        assert recorded.headers["content-length"] == str(len(payload))
        assert recorded.headers["content-type"] == "video/mp4"


# -- 308 Resume Incomplete, opt-in ----------------------------------------------------------------


def test_a_308_raises_when_resume_is_not_allowed():
    """ADR-005's default: a 3xx is an error. Unchanged unless the caller opts in."""
    with StubServer() as stub:
        stub.route("POST", "/upload", status=308, body={}, headers={"range": "bytes=0-99"})
        with pytest.raises(ProviderError) as exc:
            _http().request(
                "POST", f"{_origin(stub)}/upload", json={}, allow_private_hosts=True
            )
        assert exc.value.code == "provider_redirect"
        assert "308" in exc.value.detail


def test_a_308_returns_resume_information_when_allowed():
    with StubServer() as stub:
        stub.route(
            "POST",
            "/upload",
            status=308,
            body={},
            headers={"range": "bytes=0-99", "location": "http://127.0.0.1:1/resume/abc"},
        )
        result = _http().request(
            "POST",
            f"{_origin(stub)}/upload",
            json={},
            allow_private_hosts=True,
            allow_resume_308=True,
        )
        assert isinstance(result, ResumeInfo)
        assert result.status_code == 308
        assert result.range_header == "bytes=0-99"
        assert result.bytes_received == 100
        assert result.location.endswith("/resume/abc")


def test_a_302_still_raises_even_when_resume_is_allowed():
    """A redirect is not a resume. The flag must not become a general 3xx escape hatch."""
    with StubServer() as stub:
        stub.route("POST", "/upload", status=302, body={}, headers={"location": "http://evil.example/x"})
        with pytest.raises(ProviderError) as exc:
            _http().request(
                "POST",
                f"{_origin(stub)}/upload",
                json={},
                allow_private_hosts=True,
                allow_resume_308=True,
            )
        assert exc.value.code == "provider_redirect"
        assert "evil.example" in exc.value.detail


def test_a_307_also_still_raises_when_resume_is_allowed():
    with StubServer() as stub:
        stub.route("POST", "/upload", status=307, body={}, headers={"location": "http://evil.example/y"})
        with pytest.raises(ProviderError) as exc:
            _http().request(
                "POST", f"{_origin(stub)}/upload", json={}, allow_private_hosts=True,
                allow_resume_308=True,
            )
        assert exc.value.code == "provider_redirect"


def test_a_308_without_a_range_header_reports_zero_bytes_received():
    with StubServer() as stub:
        stub.route("POST", "/upload", status=308, body={}, headers={})
        result = _http().request(
            "POST", f"{_origin(stub)}/upload", json={}, allow_private_hosts=True,
            allow_resume_308=True,
        )
        assert result.status_code == 308
        assert result.range_header == ""
        assert result.bytes_received == 0


def test_resume_308_does_not_apply_to_a_blocked_target():
    """The flag relaxes one status code, not the address policy."""
    with pytest.raises(ProviderError) as exc:
        _http().request(
            "POST", "http://127.0.0.1:1/upload", json={}, allow_resume_308=True
        )
    assert exc.value.code == "target_blocked"


# -- a planted sentinel must not leak through the new paths ---------------------------------------


def test_a_sentinel_token_never_appears_in_a_raised_error():
    sentinel = "sf-SENTINEL-oauth-9f3a2b"
    with StubServer() as stub:
        stub.route("POST", "/token", status=401, body={"error": f"invalid_client {sentinel}"})
        with pytest.raises(ProviderError) as exc:
            _http().request(
                "POST",
                f"{_origin(stub)}/token",
                data={"grant_type": "authorization_code", "client_secret": sentinel},
                allow_private_hosts=True,
                secrets=(sentinel,),
            )
        detail = exc.value.detail
        assert sentinel not in detail
        assert "[redacted]" in detail
