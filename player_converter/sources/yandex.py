"""Yandex Music playlist source (sync, stdlib + requests only).

Mirrors the public MarshalX/yandex-music-api behaviour:
  * OAuth header auth + ``X-Yandex-Music-Client`` header
  * playlist fetch, batched full-track fetch (POST /tracks, form-encoded)
  * per-track download-info -> XML storage info -> signed direct link
    (sign = md5(SIGN_SALT + path[1:] + s))
"""

from __future__ import annotations

import os
import re
import xml.dom.minidom as minidom
from hashlib import md5
from pathlib import Path
from typing import Any

import requests

from ..models import PlaylistInfo, Track, Variant
from . import AuthError, NotFoundError, SourceError

API_BASE = "https://api.music.yandex.net"
CLIENT_HEADER = "YandexMusicAndroid/24023621"
SIGN_SALT = "XGRlBW9FXlekgbPrRHuSiA"

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


def choose_variant(variants: list[Variant], quality: str) -> Variant:
    """Pick the download variant for a quality tier.

    lossless: FLAC, falling back to the highest-bitrate variant when the
        track has no lossless version (without Plus/Premium the API
        simply does not list FLAC).
    high: MP3 320 kbps, else the best variant at/below 320.
    low: the smallest variant available.
    """
    usable = [v for v in variants if not v.preview and v.ref]
    if not usable:
        raise SourceError("no downloadable variants for this track")
    if quality == "lossless":
        flac = [v for v in usable if v.codec == "flac"]
        if flac:
            return max(flac, key=lambda v: v.bitrate_kbps)
        return max(usable, key=lambda v: v.bitrate_kbps)
    if quality == "high":
        pool = [v for v in usable if v.codec != "flac"] or usable
        exact = [v for v in pool if v.bitrate_kbps == 320]
        if exact:
            return exact[0]
        below = [v for v in pool if v.bitrate_kbps <= 320] or pool
        return max(below, key=lambda v: v.bitrate_kbps)
    if quality == "low":
        return min(usable, key=lambda v: v.bitrate_kbps)
    raise ValueError(f"unknown quality: {quality!r}")


def build_direct_link(xml: bytes) -> str:
    """Turn a download-info XML document into a signed direct link."""
    doc = minidom.parseString(xml)

    def text(tag: str) -> str:
        for el in doc.getElementsByTagName(tag):
            for node in el.childNodes:
                if node.nodeType == node.TEXT_NODE:
                    return node.data
        raise SourceError(f"download-info XML has no <{tag}>")

    host, path, ts, s = text("host"), text("path"), text("ts"), text("s")
    sign = md5((SIGN_SALT + path[1:] + s).encode("utf-8")).hexdigest()
    return f"https://{host}/get-mp3/{sign}/{ts}{path}"


class YandexSource:
    """PlaylistSource backed by api.music.yandex.net."""

    def __init__(self, token: str = "", timeout: int = 15) -> None:
        self.session = requests.Session()
        if token:
            self.session.headers.update(
                {
                    "Authorization": f"OAuth {token}",
                    "X-Yandex-Music-Client": CLIENT_HEADER,
                }
            )
        self.timeout = timeout

    def set_token(self, token: str) -> None:
        self.session.headers.update(
            {"Authorization": f"OAuth {token}", "X-Yandex-Music-Client": CLIENT_HEADER}
        )

    # -- low-level ----------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.session.request(
            method, f"{API_BASE}{path}", timeout=self.timeout, **kwargs
        )
        if resp.status_code == 401:
            raise AuthError(
                "Yandex rejected the token (401) — check YM_TOKEN / config token"
            )
        if resp.status_code == 404:
            raise NotFoundError(f"not found: {path}")
        if resp.status_code >= 400:
            raise SourceError(f"Yandex API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data.get("result", data) if isinstance(data, dict) else data

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
        try:
            result = self._request("GET", f"/tracks/{track.key}/download-info")
        except NotFoundError:
            bare = track.key.split(":")[0]
            result = self._request("GET", f"/tracks/{bare}/download-info")
        items = result if isinstance(result, list) else [result]
        variants = [
            Variant(
                codec=item.get("codec", "mp3"),
                bitrate_kbps=item.get("bitrateInKbps") or 0,
                ref=item.get("downloadInfoUrl", ""),
                preview=bool(item.get("preview")),
            )
            for item in items
        ]
        return choose_variant(variants, quality)

    def download(self, track: Track, variant: Variant, dest: Path) -> int:
        resp = self.session.get(variant.ref, timeout=self.timeout)
        resp.raise_for_status()
        url = build_direct_link(resp.content)
        tmp = dest.with_suffix(dest.suffix + ".part")
        total = 0
        with self.session.get(url, stream=True, timeout=self.timeout) as stream:
            stream.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in stream.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
        os.replace(tmp, dest)
        return total

    # -- extra ----------------------------------------------------------
    def account_login(self) -> str:
        data = self._request("GET", "/account/status")
        return data.get("account", {}).get("login", "?")
