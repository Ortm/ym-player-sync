from ym_player_sync.matching import (
    find_by_name,
    normalize,
    strip_position_prefix,
    tokens,
    track_tokens,
)
from ym_player_sync.models import Track


def _track(title="Song", artists=("Artist",)):
    return Track(key="1:1", title=title, artists=list(artists), duration_ms=1000)


def test_normalize_folds_case_punctuation_and_yo():
    assert normalize("Ёлка feat. X!") == "елка feat x"
    assert tokens("123. Song 8") == tokens("song 8 123")


def test_strip_position_prefix_variants():
    assert strip_position_prefix("001-Song") == "Song"
    assert strip_position_prefix("01. Song") == "Song"
    assert strip_position_prefix("7) Song") == "Song"
    assert strip_position_prefix("Song") == "Song"


def test_find_by_name_matches_artist_first(tmp_path):
    (tmp_path / "001-Artist - Song.mp3").write_bytes(b"x")
    found = find_by_name(tmp_path, _track(), "mp3")
    assert found is not None and found.name == "001-Artist - Song.mp3"


def test_find_by_name_matches_without_prefix(tmp_path):
    (tmp_path / "Artist - Song.mp3").write_bytes(b"x")
    assert find_by_name(tmp_path, _track(), "mp3") is not None


def test_find_by_name_ignores_extra_words(tmp_path):
    (tmp_path / "001-Artist - Song (Live).mp3").write_bytes(b"x")
    assert find_by_name(tmp_path, _track(), "mp3") is None


def test_find_by_name_requires_same_extension(tmp_path):
    (tmp_path / "001-Artist - Song.flac").write_bytes(b"x")
    assert find_by_name(tmp_path, _track(), "mp3") is None


def test_find_by_name_respects_exclude(tmp_path):
    f = tmp_path / "001-Artist - Song.mp3"
    f.write_bytes(b"x")
    assert find_by_name(tmp_path, _track(), "mp3", exclude={f}) is None


def test_track_tokens_multiple_artists_order_insensitive():
    t = _track("Duet", ("A", "B"))
    assert track_tokens(t) == tokens("A, B - Duet")
    assert track_tokens(t) == tokens("Duet - B, A")
