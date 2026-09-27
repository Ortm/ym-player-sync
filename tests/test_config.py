from pathlib import Path

import pytest

from player_converter.config import default_config_path, load_config


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


def test_token_file_is_read_when_token_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    secret = tmp_path / "ym-token"
    secret.write_text("secret-from-file\n", encoding="utf-8")
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "ym-token"')))
    assert cfg.token == "secret-from-file"
    assert cfg.token_file == secret


def test_token_file_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("YM_TOKEN_FILE", str(tmp_path / "ym-token"))
    (tmp_path / "ym-token").write_text("via-env-path", encoding="utf-8")
    cfg = load_config(
        _write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "${YM_TOKEN_FILE}"'))
    )
    assert cfg.token == "via-env-path"


def test_token_wins_over_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    (tmp_path / "ym-token").write_text("from-file", encoding="utf-8")
    cfg = load_config(
        _write(
            tmp_path,
            BASE.replace('token: "tok123"', 'token: "literal"\ntoken_file: "ym-token"'),
        )
    )
    assert cfg.token == "literal"


def test_token_file_env_file_format(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    (tmp_path / "ym-token").write_text(
        "# agenix secret\nYM_TOKEN=y0_from_env_file\n", encoding="utf-8"
    )
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "ym-token"')))
    assert cfg.token == "y0_from_env_file"


def test_token_file_env_file_with_quotes_and_export(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    (tmp_path / "ym-token").write_text("export YM_TOKEN='quoted'\n", encoding="utf-8")
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "ym-token"')))
    assert cfg.token == "quoted"


def test_token_file_other_variable_name(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    (tmp_path / "ym-token").write_text("YANDEX_TOKEN=other-name\n", encoding="utf-8")
    cfg = load_config(_write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "ym-token"')))
    assert cfg.token == "other-name"


def test_empty_token_file_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    (tmp_path / "ym-token").write_text("\n# nothing here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no token"):
        load_config(_write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "ym-token"')))


def test_unreadable_token_file_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("YM_TOKEN", raising=False)
    with pytest.raises(ValueError, match="token_file"):
        load_config(
            _write(tmp_path, BASE.replace('token: "tok123"', 'token_file: "nonexistent"'))
        )


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


def test_workers_default(tmp_path):
    assert load_config(_write(tmp_path, BASE)).workers == 4


def test_workers_explicit(tmp_path):
    cfg = load_config(_write(tmp_path, BASE + "workers: 8\n"))
    assert cfg.workers == 8


def test_workers_bad_errors(tmp_path):
    with pytest.raises(ValueError, match="workers"):
        load_config(_write(tmp_path, BASE + "workers: 0\n"))
    with pytest.raises(ValueError, match="workers"):
        load_config(_write(tmp_path, BASE + "workers: lots\n"))


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


# -- config discovery when --config is not given ---------------------------


def test_default_config_prefers_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert default_config_path() == Path("config.yaml")


def test_default_config_falls_back_to_xdg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    xdg = tmp_path / "xdg"
    (xdg / "player-converter").mkdir(parents=True)
    (xdg / "player-converter" / "config.yaml").write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert default_config_path() == xdg / "player-converter" / "config.yaml"
    # the fallback is loadable as-is (this is where the Nix module puts it)
    assert load_config(default_config_path()).quality == "high"


def test_default_config_without_xdg_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "player-converter").mkdir(parents=True)
    (home / ".config" / "player-converter" / "config.yaml").write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert default_config_path() == home / ".config" / "player-converter" / "config.yaml"


def test_default_config_falls_back_to_cwd_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    assert default_config_path() == Path("config.yaml")
    with pytest.raises(FileNotFoundError):
        load_config(default_config_path())


def test_cli_resolves_xdg_config(tmp_path, monkeypatch):
    """`player-converter info` finds the installed config without -c."""
    from player_converter import cli

    xdg = tmp_path / "xdg"
    (xdg / "player-converter").mkdir(parents=True)
    (xdg / "player-converter" / "config.yaml").write_text(
        BASE + "workers: 2\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    seen = {}

    def fake_info(config):
        seen.update(workers=config.workers)
        return 0

    monkeypatch.setattr(cli, "cmd_info", fake_info)
    assert cli.main(["info"]) == 0
    assert seen == {"workers": 2}
