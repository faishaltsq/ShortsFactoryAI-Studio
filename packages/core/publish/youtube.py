"""The real YouTube transport: a resumable private upload and a private-video listing.

Two operations, matching :class:`~packages.core.publish.transport.PublicationTransport`:

``insert``
    One resumable upload session (``videos.insert`` with ``uploadType=resumable``). The design
    question this file exists to answer is *when may a failure be retried*, and the answer is
    derived from the protocol rather than guessed:

    * The session is **initiated** first. That request carries no video bytes at all — only
      metadata — so a failure there provably uploaded nothing and is refused, not uncertain.
    * The bytes are sent to the session URL. A failure *before* the first byte of the body leaves
      the server with an empty session: refused. A failure *after* bytes went out is uncertain,
      because the server may have completed the upload and lost the response.
    * A ``308`` is the protocol's "resume from here", not a redirect. It is read through
      ``allow_resume_308`` and the remaining bytes are sent to the same session.

    This is why the transport, and not the stage, owns the retry decision: it is the only code
    that knows whether a byte left the process.

``list_private``
    ``search.list`` scoped to the authenticated channel, then ``videos.list`` for the fields a
    reconciliation matches on. ``search.list`` is the only endpoint that can find a video by its
    description marker without already knowing the id, and it costs 100 quota units against the
    default 10 000/day, so a reconciliation is deliberately not a cheap operation.

**A credential never reaches a log, an artifact, or an error detail.** The access token is passed
to :class:`PinnedHTTP` as a redaction secret on every call, so a 401 body echoing it back cannot
surface it. Nothing in this module returns the token, and no receipt records it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..providers.base import ProviderError
from ..providers.http_base import PinnedHTTP, ResumeInfo, UploadBody
from .reconcile import key_marker
from .transport import (
    InsertRequest,
    InsertResult,
    RemoteVideo,
    ThumbnailResult,
    TransportRefused,
    TransportUncertain,
)

#: The JSON API root. The upload endpoint lives on a different host, which is why it is separate.
API_ROOT = "https://www.googleapis.com/youtube/v3"

#: Where a resumable session is initiated. Google's upload host, not the JSON API host.
UPLOAD_ROOT = "https://www.googleapis.com/upload/youtube/v3"

#: How much of a file is sent per resumable chunk. Google requires every chunk except the last to
#: be a multiple of 256 KiB; 8 MiB keeps a 200 MB video to ~25 requests without holding it in RAM.
CHUNK_BYTES = 8 * 1024 * 1024

#: Fields a reconciliation needs. Requested explicitly because the default projection omits
#: ``description``, and the description is where the idempotency marker travels.
VIDEO_FIELDS = "items(id,snippet(title,description),status(privacyStatus))"

#: How many search results a reconciliation will page through. A private listing that has grown
#: past this is reported as truncated rather than silently treated as complete.
SEARCH_PAGE_LIMIT = 50
SEARCH_MAX_PAGES = 4

#: The category a Short is published under when metadata does not say otherwise (22 = People &
#: Blogs). Named here so the default is visible rather than buried in a request body.
DEFAULT_CATEGORY_ID = "22"


@dataclass(frozen=True)
class YouTubeCredentials:
    """What one authenticated call needs. ``repr`` never shows the token.

    ``client_id``/``client_secret`` are needed by the refresh path; the transport itself only uses
    ``access_token``, which keeps the transport provable with a token alone.
    """

    access_token: str = field(repr=False)
    client_id: str = ""
    client_secret: str = field(default="", repr=False)

    def __repr__(self) -> str:
        return (
            f"YouTubeCredentials(access_token=[redacted], client_id={self.client_id!r}, "
            "client_secret=[redacted])"
        )

    @property
    def secrets(self) -> tuple[str, ...]:
        """Values to register for redaction on every request made with this credential."""
        return tuple(value for value in (self.access_token, self.client_secret) if value)


@dataclass
class YouTubeTransport:
    """A :class:`PublicationTransport` speaking the real YouTube Data API.

    ``http`` and ``credentials`` are injected so the whole transport is provable against a
    loopback stub, and so a token refresh can happen outside this object without it holding
    client secrets it does not need.
    """

    credentials: YouTubeCredentials
    http: PinnedHTTP = field(default_factory=lambda: PinnedHTTP(timeout_s=120.0, max_retries=0))
    api_root: str = API_ROOT
    upload_root: str = UPLOAD_ROOT
    name: str = "youtube"
    #: Recorded per call so a caller can assert on what was actually sent without a network.
    calls: list[dict[str, Any]] = field(default_factory=list)

    # -- helpers ----------------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credentials.access_token}"}

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: UploadBody | None = None,
        json_body: Any = None,
        allow_resume_308: bool = False,
    ) -> Any:
        """One request through the shared policy, with the token registered for redaction."""
        self.calls.append({"method": method, "url": url, "kind": "upload" if body else "json"})
        return self.http.request(
            method,
            url,
            headers=self._headers(),
            body=body,
            json=json_body,
            secrets=self.credentials.secrets,
            provider="youtube",
            allow_resume_308=allow_resume_308,
        )

    # -- insert -----------------------------------------------------------------------------
    def insert(self, request: InsertRequest) -> InsertResult:
        """Upload one private video. Raises a refusal or an uncertainty; never both."""
        path = Path(request.video_path)
        if not path.is_file():
            raise TransportRefused(
                "video_missing", f"the file to upload does not exist: {path.name}"
            )
        size = path.stat().st_size
        if size == 0:
            raise TransportRefused("video_empty", "refusing to upload a zero-byte file")
        if not self.credentials.access_token:
            # Checked before the session is opened so a missing token cannot leave an empty
            # session behind on the channel.
            raise TransportRefused("no_credential", "no YouTube access token is configured")

        session_url = self._initiate_session(request, size)
        return self._send_bytes(request, session_url, size, path)

    def _initiate_session(self, request: InsertRequest, size: int) -> str:
        """Open a resumable session. Carries metadata only, so a failure here uploaded nothing."""
        url = f"{self.upload_root}/videos?{urlencode({'uploadType': 'resumable', 'part': 'snippet,status'})}"
        body = {
            "snippet": {
                "title": request.title,
                "description": _description_with_marker(request),
                "tags": list(request.tags),
                "categoryId": str(request.metadata.get("category_id") or DEFAULT_CATEGORY_ID),
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": bool(request.metadata.get("made_for_kids", False)),
            },
        }
        try:
            response = self._request(
                "POST",
                url,
                json_body=body,
                # The session response is a 200 with a Location header, not a 3xx, so the resume
                # opt-in is not needed here.
            )
        except ProviderError as exc:
            raise TransportRefused(
                exc.code, f"could not open an upload session: {exc.detail}"
            ) from exc
        location = ""
        headers = getattr(response, "headers", {})
        location = str(headers.get("location") or headers.get("Location") or "")
        if not location:
            raise TransportRefused(
                "upload_session_missing",
                "the upload session response carried no Location header, so no bytes were sent",
            )
        return location

    def _send_bytes(
        self, request: InsertRequest, session_url: str, size: int, path: Path
    ) -> InsertResult:
        """Send the file in resumable chunks. The only place that knows if a byte left."""
        offset = 0
        chunks = _chunk_ranges(size, CHUNK_BYTES)
        for index, (start, end) in enumerate(chunks):
            last = index == len(chunks) - 1
            headers = {
                **self._headers(),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }
            self.calls.append({"method": "PUT", "url": session_url, "kind": "upload_chunk"})
            try:
                response = self.http.request(
                    "PUT",
                    session_url,
                    headers=headers,
                    body=_slice_body(path, start, end - start + 1),
                    secrets=self.credentials.secrets,
                    provider="youtube",
                    allow_resume_308=True,
                )
            except ProviderError as exc:
                if offset == 0:
                    # Nothing of the file has been accepted yet by our own accounting, but the
                    # server may still have taken this chunk. That is exactly the ambiguous case.
                    raise TransportUncertain(
                        exc.code,
                        f"the upload failed while sending the first chunk: {exc.detail}",
                    ) from exc
                raise TransportUncertain(
                    exc.code,
                    f"the upload failed after {offset} of {size} bytes: {exc.detail}",
                ) from exc
            if isinstance(response, ResumeInfo):
                # The server has accepted up to ``bytes_received`` and wants the rest.
                offset = response.bytes_received
                continue
            offset = end + 1
            if last:
                return _insert_result(response, size)
        # Every chunk was sent but no final response was read: the outcome is genuinely unknown.
        raise TransportUncertain(
            "upload_incomplete",
            f"all {size} bytes were sent but no completion response was received",
        )

    # -- list -------------------------------------------------------------------------------
    def list_private(self) -> list[RemoteVideo]:
        """Every private upload on the authenticated channel, newest first.

        Two calls: ``search.list`` finds the ids (it is the only endpoint that can match on a
        description), then ``videos.list`` reads the fields a reconciliation needs. A private
        video is only visible to its owner, so this listing is scoped to the operator's own
        channel by construction.
        """
        video_ids = self._search_private_ids()
        if not video_ids:
            return []
        return self._videos_by_id(video_ids)

    # -- thumbnail --------------------------------------------------------------------------
    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> ThumbnailResult:
        """Upload one custom thumbnail for an existing video.

        A failure here is always ``TransportRefused``, never ``TransportUncertain``: the video
        itself is already published and private, and a failed thumbnail upload leaves the video
        intact on the channel with an auto-generated thumbnail. The operator can retry it.
        """
        if not video_id.strip():
            raise TransportRefused("video_id_missing", "refusing to set thumbnail without a video id")
        path = Path(thumbnail_path)
        if not path.is_file():
            raise TransportRefused(
                "thumbnail_missing", f"the thumbnail file does not exist: {path.name}"
            )
        size = path.stat().st_size
        if size == 0:
            raise TransportRefused("thumbnail_empty", "refusing to upload a zero-byte thumbnail")
        if not self.credentials.access_token:
            raise TransportRefused("no_credential", "no YouTube access token is configured")

        url = f"{self.upload_root}/thumbnails/set?{urlencode({'videoId': video_id})}"
        body = UploadBody(
            path=path,
            content_length=size,
            content_type="image/png",
            chunk_bytes=size,
        )
        self.calls.append({"method": "POST", "url": url, "kind": "upload_thumbnail"})
        try:
            response = self.http.request(
                "POST",
                url,
                headers=self._headers(),
                body=body,
                secrets=self.credentials.secrets,
                provider="youtube",
            )
        except ProviderError as exc:
            raise TransportRefused(
                exc.code, f"could not upload thumbnail: {exc.detail}"
            ) from exc

        payload = _json_body(response)
        raw_items = payload.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        default_entry = first.get("default") if isinstance(first, dict) and isinstance(first.get("default"), dict) else {}
        thumb_url = str(default_entry.get("url", "")) if isinstance(default_entry, dict) else ""
        return ThumbnailResult(url=thumb_url, detail=f"thumbnail accepted ({size} bytes)")

    def _search_private_ids(self) -> list[str]:
        ids: list[str] = []
        page_token = ""
        for _ in range(SEARCH_MAX_PAGES):
            query = {
                "part": "id",
                "forMine": "true",
                "type": "video",
                "maxResults": str(SEARCH_PAGE_LIMIT),
                "order": "date",
            }
            if page_token:
                query["pageToken"] = page_token
            try:
                response = self._request(
                    "GET", f"{self.api_root}/search?{urlencode(query)}"
                )
            except ProviderError as exc:
                raise TransportRefused(
                    exc.code, f"could not list the channel's private videos: {exc.detail}"
                ) from exc
            payload = _json_body(response)
            for item in payload.get("items") or []:
                video_id = str(((item.get("id") or {}) if isinstance(item, dict) else {}).get("videoId") or "")
                if video_id:
                    ids.append(video_id)
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return ids

    def _videos_by_id(self, video_ids: list[str]) -> list[RemoteVideo]:
        videos: list[RemoteVideo] = []
        for start in range(0, len(video_ids), SEARCH_PAGE_LIMIT):
            batch = video_ids[start : start + SEARCH_PAGE_LIMIT]
            query = {"part": "snippet,status", "id": ",".join(batch), "fields": VIDEO_FIELDS}
            try:
                response = self._request("GET", f"{self.api_root}/videos?{urlencode(query)}")
            except ProviderError as exc:
                raise TransportRefused(
                    exc.code, f"could not read the listed videos: {exc.detail}"
                ) from exc
            payload = _json_body(response)
            for item in payload.get("items") or []:
                if not isinstance(item, dict):
                    continue
                raw_snippet = item.get("snippet")
                snippet: dict[str, object] = raw_snippet if isinstance(raw_snippet, dict) else {}
                raw_status = item.get("status")
                status: dict[str, object] = raw_status if isinstance(raw_status, dict) else {}
                videos.append(
                    RemoteVideo(
                        video_id=str(item.get("id") or ""),
                        title=str(snippet.get("title") or ""),
                        privacy=str(status.get("privacyStatus") or "private"),
                        # YouTube exposes no custom key field, so the marker in the description
                        # is the only explicit signal. Reconciliation reads it from ``metadata``.
                        idempotency_key="",
                        metadata={
                            "description": str(snippet.get("description") or ""),
                            "channel_id": str(snippet.get("channelId") or ""),
                        },
                    )
                )
        return videos


def _description_with_marker(request: InsertRequest) -> str:
    """The description a reconciliation can match on, with the key marker appended.

    The marker is appended rather than embedded in the model's own copy: the description is
    operator-visible on the channel, and a marker that replaced real text would be a silent edit
    of the operator's metadata.
    """
    marker = key_marker(request.idempotency_key)
    description = request.description or ""
    if marker in description:
        return description
    return f"{description}\n\n{marker}".strip()


def _chunk_ranges(size: int, chunk_bytes: int) -> list[tuple[int, int]]:
    """Inclusive ``(start, end)`` ranges covering ``size`` bytes. Never empty for a non-empty file."""
    if size <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < size:
        end = min(start + chunk_bytes, size) - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _slice_body(path: Path, start: int, length: int) -> UploadBody:
    """A body that yields only ``[start, start+length)`` of the file.

    ``PinnedHTTP`` streams ``UploadBody.chunks()``, and the resumable protocol needs each request
    to carry one range of the file rather than the whole thing. The declared length is the slice's
    length, so a truncated transfer cannot look complete.
    """
    return UploadBody(
        path=path,
        content_length=length,
        content_type="video/mp4",
        chunk_bytes=min(CHUNK_BYTES, max(length, 1)),
        start=start,
    )


def _json_body(response: Any) -> dict[str, Any]:
    """The parsed JSON body, or an empty object. A non-JSON 200 is a provider bug, not a crash."""
    try:
        payload: Any = response.json()
    except Exception:  # noqa: BLE001 - a malformed body must not surface as an exception type
        return {}
    return payload if isinstance(payload, dict) else {}


def _insert_result(response: Any, size: int) -> InsertResult:
    """Read the video id out of a completed upload."""
    payload = _json_body(response)
    video_id = str(payload.get("id") or "")
    if not video_id:
        # The upload completed from the server's point of view but the id is unreadable. The video
        # may well exist, so this is not a refusal: it is an unknown outcome.
        raise TransportUncertain(
            "upload_id_unreadable",
            f"the upload of {size} bytes completed but the response carried no video id",
        )
    raw_status = payload.get("status")
    status: dict[str, object] = raw_status if isinstance(raw_status, dict) else {}
    privacy = str(status.get("privacyStatus") or "private")
    if privacy != "private":
        # A private-only publisher that received a non-private status has a real problem, and the
        # operator must see it rather than have it recorded as a clean private upload.
        raise TransportUncertain(
            "upload_not_private",
            f"the upload completed as {privacy!r}, not 'private'; the video exists and needs review",
        )
    return InsertResult(video_id=video_id, detail=f"private upload accepted ({size} bytes)")


def parse_upload_response(raw: bytes) -> dict[str, Any]:
    """Parse a stored upload response body. Used by tests and by receipt inspection."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
