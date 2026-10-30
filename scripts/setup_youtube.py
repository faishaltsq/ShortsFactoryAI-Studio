"""YouTube OAuth setup helper for ShortsFactoryAI Studio.

Authorizes the studio to publish private Shorts and thumbnails to YouTube via Google OAuth 2.0 PKCE.
Tokens and client secrets are DPAPI-sealed into data/secrets/.
Credentials never leak to stdout, logs, or repository.
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.api.settings import Settings  # noqa: E402
from packages.core.providers.http_base import PinnedHTTP  # noqa: E402
from packages.core.publish.oauth import (  # noqa: E402
    DEFAULT_SCOPES,
    ClientCredentials,
    build_authorize_url,
    exchange_code,
    new_pkce_verifier,
    pkce_challenge,
    seal_client_credentials,
    seal_tokens,
)
from packages.core.security.secretstore import SecretStore  # noqa: E402

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"


def _read_client_secrets(path: Path) -> tuple[str, str, list[str], str]:
    """Read client_id, client_secret, redirect_uris, and app_type from Google client_secret.json."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    app_type = "installed" if "installed" in raw else "web" if "web" in raw else ""
    if not app_type:
        raise ValueError("Invalid client_secret.json: expected 'installed' or 'web' root key")
    info = raw[app_type]
    client_id = str(info.get("client_id") or "")
    client_secret = str(info.get("client_secret") or "")
    redirect_uris = [str(u) for u in (info.get("redirect_uris") or [])]
    if not client_id or not client_secret:
        raise ValueError("client_secret.json missing client_id or client_secret")
    return client_id, client_secret, redirect_uris, app_type


class CallbackServer:
    """Single-request HTTP server waiting for the OAuth callback."""

    def __init__(self, host: str, port: int, expected_state: str) -> None:
        self.host = host
        self.port = port
        self.expected_state = expected_state
        self.auth_code: str | None = None
        self.error: str | None = None
        self._done_event = threading.Event()
        self._server: http.server.ThreadingHTTPServer | None = None

    def start(self) -> None:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass  # Suppress default request logging to avoid token leakage

            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path not in {"/callback", "/callback/"}:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not Found")
                    return

                params = urllib.parse.parse_qs(parsed.query)
                state = params.get("state", [""])[0]
                if state != outer.expected_state:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>State mismatch (anti-CSRF failure)</h1>")
                    outer.error = "State mismatch"
                    outer._done_event.set()
                    return

                err = params.get("error", [""])[0]
                if err:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(f"<h1>Authorization failed: {err}</h1>".encode())
                    outer.error = err
                    outer._done_event.set()
                    return

                code = params.get("code", [""])[0]
                if not code:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>Missing code parameter</h1>")
                    outer.error = "Missing code"
                    outer._done_event.set()
                    return

                outer.auth_code = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = (
                    "<!DOCTYPE html><html><body style='font-family: sans-serif; text-align: center; padding: 50px;'>"
                    "<h2 style='color: #16a34a;'>Otorisasi YouTube Berhasil!</h2>"
                    "<p>ShortsFactoryAI Studio telah menerima token otorisasi. Anda dapat menutup tab ini.</p>"
                    "</body></html>"
                )
                self.wfile.write(html.encode("utf-8"))
                outer._done_event.set()

        self._server = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()

    def wait_for_code(self, timeout_s: float = 300.0) -> str:
        completed = self._done_event.wait(timeout=timeout_s)
        if self._server:
            self._server.shutdown()
        if not completed:
            raise TimeoutError("Otorisasi waktu habis (timeout menunggu callback di browser).")
        if self.error:
            raise RuntimeError(f"Otorisasi ditolak atau gagal: {self.error}")
        if not self.auth_code:
            raise RuntimeError("Tidak ada authorization code yang diterima.")
        return self.auth_code


def _verify_channel(access_token: str) -> dict[str, str]:
    """Call YouTube API to verify channel access with the new token."""
    http = PinnedHTTP(timeout_s=30.0, max_retries=0)
    try:
        response = http.request(
            "GET",
            CHANNELS_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            secrets=(access_token,),
            provider="youtube",
        )
        data = response.json()
        items = data.get("items") or []
        if not items:
            return {"title": "Unknown Channel", "id": "none"}
        snippet = items[0].get("snippet") or {}
        return {"title": str(snippet.get("title") or "Unnamed"), "id": str(items[0].get("id") or "")}
    except Exception as exc:  # noqa: BLE001
        return {"title": f"Verifikasi gagal ({exc})", "id": "unknown"}


def run_setup(client_secrets_path: Path, port: int = 8765, manual_mode: bool = False) -> None:
    settings = Settings.from_env().ensure()
    secret_store = SecretStore(settings.secrets_dir)

    print(f"Membaca client secrets dari: {client_secrets_path}")
    client_id, client_secret, redirect_uris, app_type = _read_client_secrets(client_secrets_path)
    print(f"Tipe Aplikasi: {app_type}")
    print(f"Client ID: {client_id[:28]}...")

    # Seal client credentials with DPAPI immediately
    seal_client_credentials(secret_store, ClientCredentials(client_id, client_secret))
    print("Client credentials berhasil dienkripsi dan disimpan (DPAPI).")

    verifier = new_pkce_verifier()
    challenge = pkce_challenge(verifier)
    state = secrets.token_urlsafe(32)

    local_redirect = f"http://127.0.0.1:{port}/callback"
    has_local_redirect = local_redirect in redirect_uris or f"http://localhost:{port}/callback" in redirect_uris

    # Determine whether we can use automatic loopback or need manual paste / prompt
    use_automatic = not manual_mode and (app_type == "installed" or has_local_redirect)

    if not use_automatic and not manual_mode:
        print("\n" + "=" * 60)
        print("PERHATIAN: Redirect URI")
        print(f"Client ini berjenis '{app_type}' dengan URI terdaftar:")
        for uri in redirect_uris:
            print(f"  - {uri}")
        print("=" * 60)
        print("\nUntuk mode otomatis, tambahkan URI ini ke Google Cloud Console:")
        print(f"  {local_redirect}")
        print("\nPilih mode:")
        print(f"  [1] Lanjutkan Otomatis (Pastikan {local_redirect} sudah didaftarkan)")
        print("  [2] Mode Manual (Gunakan redirect URI terdaftar, lalu paste URL/code callback)")
        choice = input("\nPilihan [1/2] (default 1): ").strip()
        if choice == "2":
            manual_mode = True
            use_automatic = False
        else:
            use_automatic = True

    if use_automatic:
        redirect_uri = local_redirect
        auth_url = build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=DEFAULT_SCOPES,
            state=state,
            code_challenge=challenge,
        )
        server = CallbackServer("127.0.0.1", port, state)
        server.start()
        print(f"\nServer callback lokal mendengarkan di {local_redirect}")
        print("Membuka browser untuk otorisasi Google...")
        webbrowser.open(auth_url)
        print("\nJika browser tidak terbuka otomatis, salin dan buka URL ini:")
        print(auth_url)
        print("\nMenunggu otorisasi di browser...")
        code = server.wait_for_code()
    else:
        redirect_uri = redirect_uris[0] if redirect_uris else local_redirect
        auth_url = build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=DEFAULT_SCOPES,
            state=state,
            code_challenge=challenge,
        )
        print("\nBuka URL ini di browser untuk otorisasi Google:")
        print(auth_url)
        webbrowser.open(auth_url)
        print(f"\nSetelah login, browser akan dialihkan ke: {redirect_uri}?code=...")
        print("(Jika halaman menampilkan error dari host callback, jangan khawatir, cukup salin URL di address bar)")
        pasted = input("\nPaste URL lengkap address bar atau nilai code di sini: ").strip()
        if "code=" in pasted:
            parsed = urllib.parse.urlsplit(pasted)
            code = urllib.parse.parse_qs(parsed.query).get("code", [pasted])[0]
        else:
            code = pasted

    print("\nMelakukan penukaran authorization code dengan token...")
    http = PinnedHTTP(timeout_s=30.0, max_retries=0)
    bundle = exchange_code(
        http=http,
        token_endpoint=TOKEN_ENDPOINT,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
    )

    seal_tokens(secret_store, bundle)
    print("Token berhasil dienkripsi dan disimpan di data/secrets/oauth-youtube.bin (DPAPI)!")

    print("\nMemverifikasi koneksi channel YouTube...")
    info = _verify_channel(bundle.access_token)
    print(f"Channel: {info['title']} (ID: {info['id']})")
    print("\nSetup YouTube SELESAI. Studio siap melakukan publish dan upload thumbnail.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup YouTube OAuth credentials for ShortsFactoryAI Studio")
    default_path = Path(
        r"C:\Users\cubeb\Downloads\client_secret_27698248583-96m1fovdr38gdsfrv0voaqccoqtps9um.apps.googleusercontent.com.json"
    )
    parser.add_argument(
        "--client-secrets",
        type=Path,
        default=default_path,
        help="Path ke file client_secret JSON dari Google Cloud Console",
    )
    parser.add_argument("--port", type=int, default=8765, help="Port callback lokal (default: 8765)")
    parser.add_argument("--manual", action="store_true", help="Gunakan mode manual paste callback")
    args = parser.parse_args()

    try:
        run_setup(args.client_secrets, port=args.port, manual_mode=args.manual)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
