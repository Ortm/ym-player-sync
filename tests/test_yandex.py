import hashlib

import pytest

from player_converter.models import Variant
from player_converter.sources import detect_source, get_source
from player_converter.sources.yandex import (
    SIGN_SALT,
    build_direct_link,
    choose_variant,
    parse_playlist_url,
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


def _v(codec, bitrate, preview=False):
    return Variant(codec=codec, bitrate_kbps=bitrate, ref="http://x", preview=preview)


def test_choose_lossless_prefers_flac():
    v = choose_variant([_v("mp3", 320), _v("flac", 912)], "lossless")
    assert v.codec == "flac"


def test_choose_lossless_falls_back_to_best():
    v = choose_variant([_v("mp3", 128), _v("mp3", 320)], "lossless")
    assert (v.codec, v.bitrate_kbps) == ("mp3", 320)


def test_choose_high_prefers_320_no_flac():
    v = choose_variant([_v("flac", 912), _v("mp3", 320), _v("mp3", 128)], "high")
    assert (v.codec, v.bitrate_kbps) == ("mp3", 320)


def test_choose_low_picks_smallest():
    v = choose_variant([_v("mp3", 320), _v("aac", 64), _v("mp3", 128)], "low")
    assert (v.codec, v.bitrate_kbps) == ("aac", 64)


def test_choose_skips_previews_and_empty():
    with pytest.raises(Exception):
        choose_variant([_v("mp3", 128, preview=True)], "high")


def test_build_direct_link_signs_like_reference_client():
    xml = (
        b"<download-info><host>storage.example.net</host>"
        b"<path>/get-mp3/abc/def123</path><ts>abc123</ts><s>xyz999</s>"
        b"</download-info>"
    )
    link = build_direct_link(xml)
    expected_sign = hashlib.md5(
        (SIGN_SALT + "get-mp3/abc/def123" + "xyz999").encode()
    ).hexdigest()
    assert link == (
        f"https://storage.example.net/get-mp3/{expected_sign}/abc123/get-mp3/abc/def123"
    )


def test_variant_estimated_bytes():
    v = _v("mp3", 320)
    assert v.estimated_bytes(180_000) == 320 * 180_000 // 8000  # 7.2 MB


def test_variant_extensions():
    assert _v("flac", 900).extension == "flac"
    assert _v("mp3", 320).extension == "mp3"
    assert _v("aac", 64).extension == "m4a"
