import pytest

from player_converter.config import load_config


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


BASE = """\
playlist_url: "https://music.yandex.ru/users/u/playlists/1"
token: "tok123"
quality: high
output_dir: "./music"
player_dir: "/run/media/u/PLAYER"
"""


def test_load_ok(tmp_path):
    cfg = load_config(_write(tmp_path, BASE))
    assert cfg.quality == "high"
    assert cfg.max_tracks is None and cfg.max_total_mb is None
    assert cfg.output_dir == (tmp_path / "music").resolve()
    assert str(cfg.player_dir) == "/run/media/u/PLAYER"


def test_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("YM_TOKEN", "secret-from-env")
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"',
                                                    'token: "${YM_TOKEN}"')))
    assert cfg.token == "secret-from-env"


def test_env_fallback_when_token_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("YM_TOKEN", "fallback")
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"\n', "")))
    assert cfg.token == "fallback"


def test_missing_token_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    with pytest.raises(ValueError, match="no token"):
        load_config(_write(tmp_path, BASE.replace('token: "tok123"\n', "")))


def test_bad_quality_errors(tmp_path):
    with pytest.raises(ValueError, match="quality"):
        load_config(_write(tmp_path, BASE.replace("quality: high", "quality: ultra")))


def test_bad_url_errors(tmp_path):
    with pytest.raises(ValueError, match="playlist_url"):
        load_config(_write(tmp_path, BASE.replace(
            "https://music.yandex.ru/users/u/playlists/1", "not a url")))


def test_limits_parsed(tmp_path):
    cfg = load_config(_write(tmp_path, BASE + "max_tracks: 50\nmax_total_mb: 500\n"))
    assert cfg.max_tracks == 50 and cfg.max_total_mb == 500.0


def test_missing_file_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_source_defaults_to_autodetect(tmp_path):
    assert load_config(_write(tmp_path, BASE)).source is None


def test_source_explicit(tmp_path):
    cfg = load_config(_write(tmp_path, BASE + "source: yandex\n"))
    assert cfg.source == "yandex"


def test_source_unknown_errors(tmp_path):
    with pytest.raises(ValueError, match="source"):
        load_config(_write(tmp_path, BASE + "source: spotify\n"))
