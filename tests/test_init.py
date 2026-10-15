"""`ym-player-sync init` and the config example it shares its text with."""

from pathlib import Path

import yaml

from ym_player_sync.cli import main
from ym_player_sync.config_template import TEMPLATE

REPO = Path(__file__).resolve().parent.parent


def test_init_writes_a_commented_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0

    written = tmp_path / "config" / "config.yaml"
    assert written.is_file()
    raw = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert raw["quality"] == "lossless"
    assert raw["tags"] is True and raw["embed_cover"] is True
    assert "playlist_url" in raw and "player_dir" in raw
    # the token lines stay commented out — they are what the user fills in
    assert "token" not in raw and "token_file" not in raw


def test_init_prints_the_written_path_and_next_step(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "config/config.yaml" in out
    assert "ym-player-sync info" in out


def test_init_refuses_to_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "config" / "config.yaml"
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


def test_example_config_matches_the_template():
    """The repo's config.example.yaml is exactly what `init` writes."""
    example = REPO / "config.example.yaml"
    assert example.read_text(encoding="utf-8") == TEMPLATE
