"""Guard against version drift between the package metadata and the code."""

import tomllib
from pathlib import Path

from player_converter import __version__


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        declared = tomllib.load(f)["project"]["version"]
    assert __version__ == declared, (
        "player_converter/__init__.py and pyproject.toml disagree; "
        "the Nix package reads the version from pyproject.toml"
    )
