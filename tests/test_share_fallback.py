"""Share-link fallback: full id first, bare uuid second (no network)."""

import pytest

from player_converter.sources import AuthError, SourceError
from player_converter.sources.yandex import YandexSource

PAYLOAD = {
    "title": "Shared",
    "owner": {"login": "someone"},
    "tracks": [{"id": 1, "albumId": 2}],
}

URL = "https://music.yandex.ru/playlists/lk.abc123"


def _source_with(responses):
    src = YandexSource(token="x")
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(path)
        resp = responses[path]
        if isinstance(resp, Exception):
            raise resp
        return resp

    src._request = fake_request  # type: ignore[method-assign]
    return src, calls


def test_share_link_retries_bare_uuid_on_451():
    err = SourceError('Yandex API error 451: {"error": {"name": "x"}}')
    src, calls = _source_with({"/playlist/lk.abc123": err, "/playlist/abc123": PAYLOAD})
    playlist = src.fetch_playlist(URL)
    assert playlist.title == "Shared"
    assert playlist.track_keys == ["1:2"]
    assert calls == ["/playlist/lk.abc123", "/playlist/abc123"]


def test_share_link_raises_last_error_when_both_fail():
    err1 = SourceError("Yandex API error 451: first")
    err2 = SourceError("Yandex API error 451: second")
    src, calls = _source_with({"/playlist/lk.abc123": err1, "/playlist/abc123": err2})
    with pytest.raises(SourceError, match="blocked this shared playlist"):
        src.fetch_playlist(URL)
    assert calls == ["/playlist/lk.abc123", "/playlist/abc123"]


def test_no_retry_on_auth_error():
    src, calls = _source_with({"/playlist/lk.abc123": AuthError("bad token")})
    with pytest.raises(AuthError):
        src.fetch_playlist(URL)
    assert calls == ["/playlist/lk.abc123"]
