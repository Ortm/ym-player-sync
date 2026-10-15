"""`ym-player-sync init` and the config template it writes."""

import pytest
import yaml

from ym_player_sync.cli import main
from ym_player_sync.config_template import TEMPLATE

# Every key the config loader understands: `init` must document all of them.
CONFIG_KEYS = {
    "playlist_url",
    "source",
    "token",
    "token_file",
    "quality",
    "tags",
    "embed_cover",
    "max_tracks",
    "max_total_mb",
    "output_dir",
    "player_dir",
    "filename_template",
    "workers",
}


def test_template_documents_every_parameter():
    raw = yaml.safe_load(TEMPLATE)
    assert set(raw) == CONFIG_KEYS


def test_template_comments_every_parameter():
    """Each parameter sits under a comment block of its own."""
    for key in CONFIG_KEYS:
        block = TEMPLATE.split(f"\n{key}:")[0].rsplit("\n\n", 1)[-1]
        assert block.lstrip().startswith("#"), f"{key} has no comment"


def test_init_writes_to_the_xdg_config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert main(["init"]) == 0

    written = tmp_path / "xdg" / "ym-player-sync" / "config.yaml"
    assert written.read_text(encoding="utf-8") == TEMPLATE


def test_init_prints_the_written_path_and_next_step(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "xdg" / "ym-player-sync" / "config.yaml") in out
    assert "ym-player-sync info" in out


def test_init_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    target = tmp_path / "xdg" / "ym-player-sync" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("keep me\n", encoding="utf-8")

    assert main(["init"]) == 1
    assert target.read_text(encoding="utf-8") == "keep me\n"
    assert "already exists" in capsys.readouterr().out


def test_init_takes_an_explicit_path(tmp_path):
    target = tmp_path / "custom" / "player.yaml"
    assert main(["init", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == TEMPLATE


def test_init_reports_a_path_it_cannot_write(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")  # a file where a dir must go
    assert main(["init", str(blocker / "config.yaml")]) == 1
    assert "cannot write" in capsys.readouterr().out


def test_fresh_config_is_valid_and_asks_for_a_token(tmp_path, monkeypatch, capsys):
    """The template parses and validates; the token is all that is missing."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("YM_TOKEN", raising=False)
    assert main(["init"]) == 0

    assert main(["info"]) == 2  # nothing left to do but fill the token in
    assert "no token" in capsys.readouterr().out
