from pathlib import Path

from player_converter.limits import apply_limits
from player_converter.models import DesiredTrack, Track, Variant
from player_converter.naming import render_filename, sanitize_name
from player_converter.sync import sync_cache, sync_player


def _meta(i, title="Song", artists=("Artist",)):
    return Track(key=f"{i}:1", title=f"{title} {i}",
                 artists=list(artists), duration_ms=180_000)


def _desired(i, filename=None, codec="mp3", bitrate=320):
    m = _meta(i)
    v = Variant(codec=codec, bitrate_kbps=bitrate, extension="mp3",
                urls=["http://x"])
    return DesiredTrack(track=m, variant=v,
                        filename=filename or f"{i:03d}-Artist - Song {i}.mp3",
                        estimated_bytes=v.estimated_bytes(m.duration_ms))


def test_sanitize_fat32():
    assert sanitize_name('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize_name("  spaced   out  ") == "spaced out"


def test_render_filename_numbering():
    name = render_filename("{position:0{width}d}-{name}.{ext}", 1, 3,
                           _meta(1), "flac")
    assert name == "001-Song 1 - Artist.flac"


def test_render_filename_default_template():
    name = render_filename("{position:0{width}d}-{title} - {artists}.{ext}", 2, 3,
                           _meta(2), "mp3")
    assert name == "002-Song 2 - Artist.mp3"


def test_apply_limits_tracks():
    assert apply_limits([1, 2, 3], [1, 1, 1], 2, None) == [1, 2]


def test_apply_limits_size_keeps_fitting():
    # sizes 10, 10, 10 with cap 25 -> first two fit
    assert apply_limits(["a", "b", "c"], [10, 10, 10], None, 25 / 1_048_576) == ["a", "b"]


def test_apply_limits_size_always_keeps_first():
    assert apply_limits(["a", "b"], [100, 1], None, 50 / 1_048_576) == ["a"]


def _fake_download(content=b"audio-bytes"):
    def download(desired, dest):
        dest.write_bytes(content)
        return len(content)
    return download


def test_sync_cache_downloads_and_reuses(tmp_path):
    cache = tmp_path / "music"
    items = [_desired(1), _desired(2)]
    counts = sync_cache(cache, items, _fake_download(), dry_run=False)
    assert counts.downloaded == 2
    assert (cache / items[0].filename).is_file()
    # second run: everything skipped
    counts = sync_cache(cache, items, _fake_download(), dry_run=False)
    assert counts.skipped == 2 and counts.downloaded == 0


def test_sync_cache_renames_on_reorder_without_redownload(tmp_path):
    cache = tmp_path / "music"
    first = [_desired(1, "001-Artist - Song 1.mp3"),
             _desired(2, "002-Artist - Song 2.mp3")]
    sync_cache(cache, first, _fake_download(b"data1"), dry_run=False)
    # playlist reordered: same tracks, swapped positions
    second = [_desired(2, "001-Artist - Song 2.mp3"),
              _desired(1, "002-Artist - Song 1.mp3")]
    seen = []

    def fail_download(desired, dest):
        seen.append(desired)
        raise AssertionError("should not re-download")

    counts = sync_cache(cache, second, fail_download, dry_run=False)
    assert counts.renamed == 2 and not seen
    assert (cache / "001-Artist - Song 2.mp3").is_file()
    assert not (cache / "002-Artist - Song 2.mp3").exists()


def test_sync_cache_removes_dropped_tracks(tmp_path):
    cache = tmp_path / "music"
    sync_cache(cache, [_desired(1), _desired(2)], _fake_download(), dry_run=False)
    counts = sync_cache(cache, [_desired(1)], _fake_download(), dry_run=False)
    assert counts.removed_cache == 1
    assert (cache / _desired(1).filename).is_file()


def test_sync_cache_dry_run_changes_nothing(tmp_path):
    cache = tmp_path / "music"
    counts = sync_cache(cache, [_desired(1)], _fake_download(), dry_run=True)
    assert counts.downloaded == 1  # reported...
    assert not cache.exists() or not any(cache.iterdir())  # ...but not done


def test_sync_player_mirrors_exactly(tmp_path):
    cache = tmp_path / "music"
    player = tmp_path / "player"
    player.mkdir()
    sync_cache(cache, [_desired(1), _desired(2)], _fake_download(), dry_run=False)
    (player / "old-song.mp3").write_bytes(b"stale")
    (player / "notes.txt").write_text("not music, must survive")

    counts = sync_player(cache, player, dry_run=False)
    assert counts.copied == 2 and counts.removed_player == 1
    assert (player / _desired(1).filename).is_file()
    assert not (player / "old-song.mp3").exists()
    assert (player / "notes.txt").is_file()  # non-audio untouched

    # second run: all skipped
    counts = sync_player(cache, player, dry_run=False)
    assert counts.skipped == 2 and counts.copied == 0


def test_sync_cache_failure_skips_track_and_retries_next_run(tmp_path):
    cache = tmp_path / "music"
    items = [_desired(1), _desired(2)]

    def flaky(desired, dest):
        if desired.track.key == "1:1":
            raise RuntimeError("boom")
        dest.write_bytes(b"ok")
        return 2

    counts = sync_cache(cache, items, flaky, dry_run=False)
    assert counts.failed == 1 and counts.downloaded == 1
    assert not (cache / items[0].filename).exists()

    # next run retries the failed track
    counts = sync_cache(cache, items, _fake_download(), dry_run=False)
    assert counts.downloaded == 1 and counts.failed == 0
    assert (cache / items[0].filename).is_file()


def test_sync_player_deletes_before_copying(tmp_path, monkeypatch):
    import shutil

    cache = tmp_path / "music"
    player = tmp_path / "player"
    cache.mkdir()
    player.mkdir()
    (cache / "001-new.mp3").write_bytes(b"new")
    (player / "999-old.mp3").write_bytes(b"old")
    events = []
    real_copy = shutil.copy2

    def rec_copy(src, dst):
        events.append(("copy", Path(dst).name))
        return real_copy(src, dst)

    orig_unlink = Path.unlink

    def rec_unlink(self):
        events.append(("del", self.name))
        return orig_unlink(self)

    monkeypatch.setattr(shutil, "copy2", rec_copy)
    monkeypatch.setattr(Path, "unlink", rec_unlink)
    counts = sync_player(cache, player, dry_run=False)
    assert events[0] == ("del", "999-old.mp3")
    assert ("copy", "001-new.mp3") in events
    assert counts.removed_player == 1 and counts.copied == 1


def test_sync_player_copy_failure_skips_track(tmp_path, monkeypatch):
    import shutil

    cache = tmp_path / "music"
    player = tmp_path / "player"
    cache.mkdir()
    player.mkdir()
    (cache / "001-song.mp3").write_bytes(b"data")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)
    counts = sync_player(cache, player, dry_run=False)
    assert counts.failed == 1 and counts.copied == 0
    assert not (player / "001-song.mp3").exists()


def test_sync_cache_parallel_matches_sequential(tmp_path):
    import threading

    cache = tmp_path / "music"
    items = [_desired(i) for i in (1, 2, 3, 4)]
    seen_threads = set()

    def download(desired, dest):
        seen_threads.add(threading.get_ident())
        dest.write_bytes(b"data")
        return 4

    counts = sync_cache(cache, items, download, dry_run=False, workers=4)
    assert counts.downloaded == 4 and counts.failed == 0
    for item in items:
        assert (cache / item.filename).is_file()
    assert len(seen_threads) > 1  # actually ran in parallel


def test_sync_cache_parallel_tolerates_failures(tmp_path):
    cache = tmp_path / "music"
    items = [_desired(i) for i in (1, 2, 3)]

    def flaky(desired, dest):
        if desired.track.key == "2:1":
            raise RuntimeError("boom")
        dest.write_bytes(b"ok")
        return 2

    counts = sync_cache(cache, items, flaky, dry_run=False, workers=3)
    assert counts.downloaded == 2 and counts.failed == 1
    assert not (cache / items[1].filename).exists()
    assert (cache / items[0].filename).is_file()
