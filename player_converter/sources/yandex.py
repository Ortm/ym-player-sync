"""Yandex Music playlist source (requests + pycryptodome only).

Metadata (playlist, tracks) goes through api.music.yandex.net like the
public MarshalX/yandex-music-api client. File downloads use the newer
official-client flow from llistochek/yandex-music-downloader:
signed ``GET /get-file-info`` -> encrypted ``encraw`` transport URLs ->
AES-CTR decryption.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random
import re
import time
from pathlib import Path
from typing import Any

import requests
from Crypto.Cipher import AES
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import PlaylistInfo, Track, Variant
from . import AuthError, SourceError

API_BASES = (
    "https://api.music.yandex.net",
    "https://api.music.yandex.ru",
    "https://api.music.yandex.com",
)
CLIENT_HEADER = "YandexMusicAndroid/24023621"

# HMAC key of the official Android app (same public key yandex-music-api
# and yandex-music-downloader use for file-info request signing).
SIGN_KEY = "p93jhgh689SBReK6ghtw62"

# quality tier -> get-file-info quality value
QUALITY_VALUES = {"lossless": "lossless", "high": "nq", "low": "lq"}
FILE_CODECS = "flac,flac-mp4,mp3,aac,he-aac,aac-mp4,he-aac-mp4"

# server codec -> output file extension (container decides)
CONTAINER_EXTENSIONS = {
    "flac": "flac",
    "flac-mp4": "m4a",
    "mp3": "mp3",
    "aac": "m4a",
    "he-aac": "m4a",
    "aac-mp4": "m4a",
    "he-aac-mp4": "m4a",
}

# music.yandex.ru/users/<user>/playlists/<kind>
_RE_USER_PLAYLIST = re.compile(r"music\.yandex\.[a-z]+/users/([^/]+)/playlists/(\d+)")
# music.yandex.ru/playlists/<uid>.<uuid> (share links, e.g. .../playlists/lk.<uuid>)
_RE_SHARE_PLAYLIST = re.compile(r"music\.yandex\.[a-z]+/playlists/([A-Za-z0-9_.-]+)")
# music.yandex.ru/playlist/<uuid> (public share links)
_RE_UUID_PLAYLIST = re.compile(r"music\.yandex\.[a-z]+/playlist/([0-9a-f-]+)")


def parse_playlist_url(url: str) -> tuple[str, str]:
    """Return ("user", "login/kind") or ("uuid", "<playlist uuid>")."""
    m = _RE_USER_PLAYLIST.search(url)
    if m:
        return ("user", f"{m.group(1)}/{m.group(2)}")
    m = _RE_SHARE_PLAYLIST.search(url)
    if m:
        return ("uuid", m.group(1))
    m = _RE_UUID_PLAYLIST.search(url)
    if m:
        return ("uuid", m.group(1))
    raise ValueError(
        "unsupported playlist URL (expected "
        "music.yandex.ru/users/<login>/playlists/<kind>, "
        "music.yandex.ru/playlists/<uid>.<uuid> or "
        "music.yandex.ru/playlist/<uuid>)"
    )


def sign_file_info_params(params: dict[str, Any], timestamp: int | None = None) -> dict[str, Any]:
    """HMAC-sign get-file-info params (signed copy returned)."""
    params = dict(params)
    params["ts"] = timestamp if timestamp is not None else int(time.time())
    message = "".join(str(v) for v in params.values()).replace(",", "")
    digest = hmac.new(SIGN_KEY.encode(), message.encode(), hashlib.sha256).digest()
    params["sign"] = base64.b64encode(digest).decode()[:-1]
    return params


def decrypt_data(data: bytes, key: str) -> bytes:
    """AES-CTR decrypt an encraw transport payload."""
    aes = AES.new(key=bytes.fromhex(key), nonce=bytes(12), mode=AES.MODE_CTR)
    return aes.decrypt(data)


class YandexSource:
    """PlaylistSource backed by api.music.yandex.net."""

    def __init__(self, token: str = "", timeout: int = 15) -> None:
        self.session = requests.Session()
        # Transient network blips (DNS, resets, 5xx) are retried with
        # backoff instead of failing the whole sync.
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        if token:
            self.session.headers.update(
                {
                    "Authorization": f"OAuth {token}",
                    "X-Yandex-Music-Client": CLIENT_HEADER,
                }
            )
        self.timeout = timeout
        self.api_base = API_BASES[0]  # updated to whichever mirror answers

    def set_token(self, token: str) -> None:
        self.session.headers.update(
            {"Authorization": f"OAuth {token}", "X-Yandex-Music-Client": CLIENT_HEADER}
        )

    # -- low-level ----------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # If one API host is unreachable from this network (DNS/SNI
        # blocking, broken IPv6, outage), fail over to the next mirror.
        last_error: SourceError | None = None
        for base in API_BASES:
            try:
                resp = self.session.request(
                    method, f"{base}{path}", timeout=self.timeout, **kwargs
                )
            except requests.ConnectionError as e:
                last_error = SourceError(f"cannot reach {base}: {e.__class__.__name__}")
                continue
            except requests.Timeout as e:
                last_error = SourceError(f"{base} timed out: {e.__class__.__name__}")
                continue
            if resp.status_code == 401:
                raise AuthError(
                    "Yandex rejected the token (401) — check YM_TOKEN / config token"
                )
            if resp.status_code == 404:
                from . import NotFoundError

                raise NotFoundError(f"not found: {path}")
            if resp.status_code >= 400:
                raise SourceError(
                    f"Yandex API error {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            self.api_base = base  # remember the working mirror
            return data.get("result", data) if isinstance(data, dict) else data
        raise SourceError(
            "no Yandex Music API host reachable (tried "
            f"{', '.join(API_BASES)}) — check your connection, DNS, or VPN "
            f"and try again ({last_error})"
        ) from last_error

    # -- PlaylistSource ------------------------------------------------
    def fetch_playlist(self, url: str) -> PlaylistInfo:
        kind, ref = parse_playlist_url(url)
        if kind == "user":
            login, playlist_kind = ref.split("/")
            data = self._request("GET", f"/users/{login}/playlists/{playlist_kind}")
        else:
            # Share links look like lk.<uuid>; the API sometimes wants the
            # full id, sometimes the bare uuid — try both.
            candidates = [ref]
            bare = ref.rsplit(".", 1)[-1]
            if bare != ref:
                candidates.append(bare)
            data = None
            error: SourceError | None = None
            for candidate in candidates:
                try:
                    data = self._request("GET", f"/playlist/{candidate}")
                    break
                except AuthError:
                    raise
                except SourceError as e:
                    error = e
            if data is None:
                if error is not None and "451" in str(error):
                    raise SourceError(
                        "Yandex blocked this shared playlist in your region "
                        "(HTTP 451). Open the playlist while logged into "
                        "Yandex Music in your browser and use the canonical "
                        "URL instead: "
                        "music.yandex.ru/users/<your-login>/playlists/<number>"
                    ) from error
                raise error if error else SourceError(f"playlist not found: {ref}")
        keys = []
        for entry in data.get("tracks") or []:
            track_id, album_id = entry.get("id"), entry.get("albumId")
            if track_id is not None and album_id is not None:
                keys.append(f"{track_id}:{album_id}")
        return PlaylistInfo(
            title=data.get("title", "?"),
            owner=(data.get("owner") or {}).get("login", "?"),
            track_keys=keys,
        )

    def fetch_tracks(self, keys: list[str]) -> list[Track]:
        tracks: list[Track] = []
        for i in range(0, len(keys), 100):
            chunk = keys[i : i + 100]
            result = self._request(
                "POST",
                "/tracks",
                data=[("track-ids", k) for k in chunk] + [("with-positions", "True")],
            )
            items = result if isinstance(result, list) else [result]
            for item in items:
                if item.get("available") is False:
                    continue  # region-locked / removed
                artists = [
                    a.get("name", "")
                    for a in item.get("artists") or []
                    if a.get("name")
                ]
                tid = item.get("id")
                albums = item.get("albums") or []
                aid = albums[0].get("id") if albums else 0
                tracks.append(
                    Track(
                        key=f"{tid}:{aid}",
                        title=item.get("title", f"track-{tid}"),
                        artists=artists,
                        duration_ms=item.get("durationMs") or 0,
                    )
                )
        return tracks

    def pick_variant(self, track: Track, quality: str) -> Variant:
        """Ask get-file-info for the track at the requested tier. The
        server replies with the actual codec/bitrate/URLs, so estimates
        built from the result are exact, not guessed."""
        try:
            quality_value = QUALITY_VALUES[quality]
        except KeyError:
            raise ValueError(f"unknown quality: {quality!r}")
        track_id = track.key.split(":")[0]
        params = sign_file_info_params(
            {
                "trackId": track_id,
                "quality": quality_value,
                "codecs": FILE_CODECS,
                "transports": "encraw",
            }
        )
        result = self._request("GET", "/get-file-info", params=params)
        info = result.get("downloadInfo", result) if isinstance(result, dict) else {}
        codec = info.get("codec", "mp3")
        try:
            extension = CONTAINER_EXTENSIONS[codec]
        except KeyError:
            raise SourceError(f"unknown codec in file info: {codec!r}")
        urls = info.get("urls") or []
        if not urls:
            raise SourceError("get-file-info returned no download URLs")
        return Variant(
            codec=codec,
            bitrate_kbps=info.get("bitrate") or 0,
            extension=extension,
            urls=list(urls),
            decrypt_key=info.get("key"),
        )

    def download(self, track: Track, variant: Variant, dest: Path) -> int:
        data = self._retrieve(random.choice(variant.urls))
        if variant.decrypt_key:
            data = decrypt_data(data, variant.decrypt_key)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return len(data)

    def _retrieve(self, url: str) -> bytes:
        with self.session.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            chunks = [c for c in resp.iter_content(1 << 20) if c]
        return b"".join(chunks)

    # -- extra ----------------------------------------------------------
    def account_login(self) -> str:
        data = self._request("GET", "/account/status")
        return data.get("account", {}).get("login", "?")
