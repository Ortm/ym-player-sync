"""Tag writing: what mpd/rmpc and the player read out of a downloaded file."""

from __future__ import annotations

import mutagen
import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from ym_player_sync.models import Track
from ym_player_sync.tags import (
    COVER,
    KEYS,
    Tagger,
    TagError,
    missing_fields,
    tag_values,
    write_fields,
)

ARTIST = "Кино"
ALBUM = "Группа крови"  # non-ASCII: the tags (and their encoding) must survive


def _track(**overrides) -> Track:
    fields = dict(
        key="123:456",
        title="Закрытые двери",
        artists=[ARTIST],
        duration_ms=180_000,
        album=ALBUM,
        album_artists=[ARTIST],
        year=1988,
        track_number=3,
        disc_number=1,
        cover_uri="avatars.yandex.net/get-music-content/123/%%",
    )
    fields.update(overrides)
    return Track(**fields)


def _easy(path):
    """Tags as any other player reads them (mutagen's canonical names)."""
    return mutagen.File(path, easy=True).tags


def test_tag_values_full():
    assert tag_values(_track()) == {
        "title": "Закрытые двери",
        "artist": ARTIST,
        "album": ALBUM,
        "albumartist": ARTIST,
        "date": "1988",
        "tracknumber": "3",
        "discnumber": "1",
    }


def test_tag_values_drops_fields_the_track_has_no_data_for():
    # a track the source knows nothing about beyond its own name
    assert tag_values(Track(key="1:1", title="Song")) == {"title": "Song"}


def test_tag_values_falls_back_to_the_track_artists():
    values = tag_values(Track(key="1:1", title="Song", artists=["A", "B"]))
    assert values["artist"] == "A; B"
    assert values["albumartist"] == "A; B"


@pytest.mark.parametrize("extension", ["flac", "mp3", "m4a"])
def test_write_round_trips_in_every_container(make_audio, tmp_path, extension):
    path = make_audio(tmp_path / f"003-Song.{extension}")
    write_fields(path, _track())

    tags = _easy(path)
    assert tags["title"] == ["Закрытые двери"]
    assert tags["artist"] == [ARTIST]
    assert tags["album"] == [ALBUM]
    assert tags["albumartist"] == [ARTIST]
    assert tags["date"] == ["1988"]
    assert tags["tracknumber"] == ["3"]
    assert tags["discnumber"] == ["1"]
    # nothing left to do on a re-run
    assert missing_fields(path, _track(), want_cover=False) == []


@pytest.mark.parametrize("extension", ["flac", "mp3", "m4a"])
def test_write_embeds_the_cover(make_audio, tmp_path, cover_jpeg, extension):
    path = make_audio(tmp_path / f"003-Song.{extension}")
    write_fields(path, _track(), cover=cover_jpeg)

    assert missing_fields(path, _track()) == []  # COVER included
    if extension == "flac":
        from mutagen.flac import FLAC

        pictures = FLAC(path).pictures
        assert [(p.type, p.mime) for p in pictures] == [(3, "image/jpeg")]
        assert pictures[0].data == cover_jpeg
    elif extension == "mp3":
        apic = ID3(path).getall("APIC")
        assert [(a.type, a.mime) for a in apic] == [(3, "image/jpeg")]
        assert apic[0].data == cover_jpeg
    else:
        covers = MP4(path).tags["covr"]
        assert bytes(covers[0]) == cover_jpeg


def test_mp3_tags_are_written_as_v23(make_audio, tmp_path):
    # the version cheap USB players actually read
    path = make_audio(tmp_path / "003-Song.mp3")
    write_fields(path, _track())
    assert ID3(path).version[:2] == (2, 3)


def test_write_keeps_foreign_tags(make_audio, tmp_path):
    path = make_audio(tmp_path / "003-Song.flac")
    audio = mutagen.File(path, easy=True)
    assert audio is not None
    audio["genre"] = ["rock"]
    audio.save()

    write_fields(path, _track())
    assert _easy(path)["genre"] == ["rock"]
    assert _easy(path)["album"] == [ALBUM]


def test_missing_fields_reports_only_what_is_missing(make_audio, tmp_path, cover_jpeg):
    path = make_audio(tmp_path / "003-Song.flac")
    assert set(missing_fields(path, _track(), want_cover=False)) == set(
        tag_values(_track())
    )

    write_fields(path, _track(), cover=cover_jpeg)
    assert missing_fields(path, _track()) == []
    # a changed source value (here: another album) is picked up again
    assert missing_fields(path, _track(album="Другое")) == ["album"]


def test_missing_fields_ignores_covers_when_they_are_not_wanted(
    make_audio, tmp_path
):
    path = make_audio(tmp_path / "003-Song.flac")
    write_fields(path, _track())
    assert COVER not in missing_fields(path, _track(), want_cover=False)
    assert COVER in missing_fields(path, _track(), want_cover=True)


def test_tagger_writes_once_and_fetches_one_cover_per_album(
    make_audio, tmp_path, cover_jpeg
):
    fetched = []

    def provider(track):
        fetched.append(track.key)
        return cover_jpeg

    tagger = Tagger(cover_provider=provider)
    first = make_audio(tmp_path / "001-Song.flac")
    second = make_audio(tmp_path / "002-Other.flac")

    assert tagger.apply(first, _track()) is True
    assert tagger.apply(second, _track(key="124:456", title="Другая")) is True
    assert fetched == ["123:456"]  # second track reuses the album's cover

    assert tagger.apply(first, _track()) is False  # up to date: no rewrite
    assert tagger.apply(second, _track(key="124:456", title="Другая")) is False


def test_tagger_dry_run_reports_without_writing(make_audio, tmp_path):
    path = make_audio(tmp_path / "003-Song.flac")
    before = path.read_bytes()
    tagger = Tagger()

    assert tagger.apply(path, _track(), dry_run=True) is True
    assert path.read_bytes() == before  # ... but nothing was written

    assert tagger.apply(path, _track()) is True  # a real run writes
    assert path.read_bytes() != before
    assert tagger.apply(path, _track(), dry_run=True) is False  # all up to date


def test_tagger_without_a_cover_provider_writes_text_tags_only(
    make_audio, tmp_path
):
    path = make_audio(tmp_path / "003-Song.flac")
    tagger = Tagger()
    assert tagger.pending(path, _track()) == list(tag_values(_track()))
    assert tagger.apply(path, _track()) is True
    assert _easy(path)["album"] == [ALBUM]
    assert tagger.apply(path, _track()) is False


def test_tagger_survives_a_failing_cover_fetch(make_audio, tmp_path):
    path = make_audio(tmp_path / "003-Song.flac")

    def boom(track):
        raise RuntimeError("cdn unreachable")

    tagger = Tagger(cover_provider=boom)
    assert tagger.apply(path, _track()) is True
    assert _easy(path)["title"] == ["Закрытые двери"]  # text tags still land
    assert COVER in tagger.pending(path, _track())  # ... so the next run retries

    # a retry costs one failed request and nothing else: the file is not
    # rewritten (a rewrite would push it to the player again)
    before = path.read_bytes()
    assert tagger.apply(path, _track()) is False
    assert path.read_bytes() == before


def test_unknown_container_raises(tmp_path):
    path = tmp_path / "song.ogg"
    path.write_bytes(b"OggS not really")
    with pytest.raises(TagError, match="tags are written for"):
        write_fields(path, _track())
    with pytest.raises(TagError, match="tags are written for"):
        missing_fields(path, _track())


def test_non_audio_bytes_raise(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"not an mpeg stream at all")
    with pytest.raises(TagError):
        write_fields(path, _track())


def test_keys_cover_every_supported_container():
    from ym_player_sync.tags import _OPENERS

    assert set(KEYS) == set(_OPENERS)
    for keys in KEYS.values():
        assert set(keys) == set(tag_values(_track()))
