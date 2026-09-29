"""Share-link fallback: full id first, bare uuid second (no network)."""

import pytest

from ym_player_sync.sources import AuthError, SourceError
from ym_player_sync.sources.yandex import YandexSource

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


def test_parse_likes_url():
    from ym_player_sync.sources.yandex import parse_playlist_url

    assert parse_playlist_url("https://music.yandex.ru/users/example-user/tracks") == (
        "likes",
        "example-user",
    )


def test_likes_playlist_reads_library_tracks():
    src = YandexSource(token="x")
    seen = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        return {"library": {"tracks": [{"id": 7, "albumId": 8}], "revision": 1}}

    src._request = fake_request  # type: ignore[method-assign]
    playlist = src.fetch_playlist("https://music.yandex.ru/users/example-user/tracks")
    assert playlist.track_keys == ["7:8"]
    assert playlist.owner == "example-user"
    assert seen == ["/users/example-user/likes/tracks"]


def test_shared_playlist_refetches_owner_context_when_trackless():
    src = YandexSource(token="x")
    seen = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        if path == "/playlist/lk.abc123":
            return {"title": "Liked", "owner": {"login": "u"}, "kind": 3, "tracks": []}
        if path == "/users/u/playlists/3":
            return {
                "title": "Liked",
                "owner": {"login": "u"},
                "tracks": [{"id": 1, "albumId": 2}],
            }
        raise AssertionError(f"unexpected {path}")

    src._request = fake_request  # type: ignore[method-assign]
    playlist = src.fetch_playlist(URL)
    assert playlist.track_keys == ["1:2"]
    assert seen == ["/playlist/lk.abc123", "/users/u/playlists/3"]
