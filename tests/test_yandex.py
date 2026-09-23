import base64
import hashlib
import hmac

import pytest
from Crypto.Cipher import AES

from player_converter.models import Track, Variant
from player_converter.sources import detect_source, get_source
from player_converter.sources.yandex import (
    CONTAINER_EXTENSIONS,
    QUALITY_VALUES,
    SIGN_KEY,
    YandexSource,
    decrypt_data,
    parse_playlist_url,
    sign_file_info_params,
)


def test_parse_user_playlist_url():
    kind, ref = parse_playlist_url(
        "https://music.yandex.ru/users/some.login/playlists/1234"
    )
    assert (kind, ref) == ("user", "some.login/1234")


def test_parse_uuid_playlist_url():
    kind, ref = parse_playlist_url(
        "https://music.yandex.ru/playlist/0e5a1b2c-3d4e-5f60-7890-abcdef123456"
    )
    assert kind == "uuid"


def test_parse_share_playlist_url_with_query():
    kind, ref = parse_playlist_url(
        "https://music.yandex.ru/playlists/lk.35ed5a38-6df4-4ab9-901e-976bd0658ce1"
        "?utm_source=web&utm_medium=copy_link"
    )
    assert (kind, ref) == (
        "uuid",
        "lk.35ed5a38-6df4-4ab9-901e-976bd0658ce1",
    )


def test_parse_bad_url():
    with pytest.raises(ValueError):
        parse_playlist_url("https://music.yandex.ru/album/12345")


def test_detect_source_yandex():
    assert detect_source("https://music.yandex.ru/users/u/playlists/1") is not None


def test_detect_source_unknown():
    with pytest.raises(ValueError):
        detect_source("https://open.spotify.com/playlist/abc")


def test_get_source_unknown():
    with pytest.raises(ValueError):
        get_source("spotify")


def test_quality_tiers_map_to_file_info_values():
    assert QUALITY_VALUES == {"lossless": "lossless", "high": "nq", "low": "lq"}


def test_sign_matches_downloader_algorithm():
    params = {"trackId": "123", "quality": "nq", "codecs": "a,b", "transports": "encraw"}
    signed = sign_file_info_params(params, timestamp=1_700_000_000)
    assert signed["ts"] == 1_700_000_000
    assert set(signed) == {*params, "ts", "sign"}
    assert list(signed)[0] == "ts"  # server requires ts first in the message
    message = f"1700000000123nqabencraw"
    expected = base64.b64encode(
        hmac.new(SIGN_KEY.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()[:-1]
    assert signed["sign"] == expected


def test_decrypt_round_trip():
    key = "00112233445566778899aabbccddeeff"
    aes = AES.new(key=bytes.fromhex(key), nonce=bytes(12), mode=AES.MODE_CTR)
    ciphertext = aes.encrypt(b"audio-bytes")
    assert decrypt_data(ciphertext, key) == b"audio-bytes"


def test_container_extensions_cover_server_codecs():
    for codec in ("flac", "flac-mp4", "mp3", "aac", "he-aac", "aac-mp4", "he-aac-mp4"):
        assert CONTAINER_EXTENSIONS[codec] in ("flac", "mp3", "m4a")


def _source_with(responses):
    src = YandexSource(token="x")
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("params")))
        resp = responses[(method, path)]
        if isinstance(resp, Exception):
            raise resp
        return resp

    src._request = fake_request  # type: ignore[method-assign]
    return src, calls


def _track():
    return Track(key="123:456", title="Song", artists=["Artist"], duration_ms=180_000)


def test_pick_variant_builds_from_file_info():
    payload = {
        "downloadInfo": {
            "quality": "nq",
            "codec": "mp3",
            "urls": ["http://a", "http://b"],
            "bitrate": 320,
        }
    }
    src, calls = _source_with({("GET", "/get-file-info"): payload})
    variant = src.pick_variant(_track(), "high")
    assert variant.codec == "mp3"
    assert variant.bitrate_kbps == 320
    assert variant.extension == "mp3"
    assert variant.urls == ["http://a", "http://b"]
    assert variant.decrypt_key is None
    method, path, params = calls[0]
    assert (method, path) == ("GET", "/get-file-info")
    assert params["trackId"] == "123"  # bare track id, not "123:456"
    assert params["quality"] == "nq"
    assert "sign" in params


def test_pick_variant_unknown_codec_errors():
    payload = {"downloadInfo": {"codec": "opus", "urls": ["http://a"], "bitrate": 160}}
    src, _ = _source_with({("GET", "/get-file-info"): payload})
    with pytest.raises(Exception, match="unknown codec"):
        src.pick_variant(_track(), "high")


def test_pick_variant_unknown_quality_errors():
    src, _ = _source_with({})
    with pytest.raises(ValueError, match="unknown quality"):
        src.pick_variant(_track(), "ultra")


def test_variant_estimated_bytes():
    v = Variant(codec="mp3", bitrate_kbps=320, extension="mp3", urls=["http://x"])
    assert v.estimated_bytes(180_000) == 320 * 180_000 // 8000  # 7.2 MB


def test_connection_error_becomes_source_error():
    import requests

    src = YandexSource(token="x")

    def fail(*args, **kwargs):
        raise requests.ConnectionError("dns blew up")

    src.session.request = fail  # type: ignore[method-assign]
    with pytest.raises(Exception, match="no Yandex Music API host reachable"):
        src.fetch_playlist("https://music.yandex.ru/users/u/playlists/1")


def test_fails_over_to_next_api_host():
    import requests

    src = YandexSource(token="x")
    seen = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"result": {"ok": True}}

    def fake_request(method, url, **kwargs):
        seen.append(url)
        if "yandex.net" in url:
            raise requests.ConnectionError("blocked")
        return FakeResp()

    src.session.request = fake_request  # type: ignore[method-assign]
    assert src._request("GET", "/account/status") == {"ok": True}
    assert seen[0].startswith("https://api.music.yandex.net/")
    assert seen[1].startswith("https://api.music.yandex.ru/")
    assert src.api_base == "https://api.music.yandex.ru"


class _FakeStreamResp:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.payload


def test_retrieve_falls_over_to_next_url(tmp_path, monkeypatch):
    import random
    import time

    import requests

    from player_converter.sources import SourceError

    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(random, "shuffle", lambda x: None)
    src = YandexSource(token="x")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "host-a" in url:
            raise requests.ConnectionError("stalled")
        return _FakeStreamResp(b"bytes")

    src.session.get = fake_get  # type: ignore[method-assign]
    track = _track()
    data = src._retrieve_with_fallback(
        track, ["https://host-a/file", "https://host-b/file"]
    )
    assert data == b"bytes"
    assert calls[0] == "https://host-a/file"
    assert calls[-1] == "https://host-b/file"

    def always_down(url, **kwargs):
        raise requests.ConnectionError("down")

    src.session.get = always_down  # type: ignore[method-assign]
    with pytest.raises(SourceError, match="download failed"):
        src._retrieve_with_fallback(track, ["https://host-a/file"])
