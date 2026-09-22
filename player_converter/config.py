"""YAML config loading and validation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .sources import AVAILABLE_SOURCES

VALID_QUALITIES = ("lossless", "high", "low")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """Expand ${VAR} in strings using the environment (unknown vars -> '')."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class Config:
    playlist_url: str
    token: str
    quality: str
    max_tracks: int | None
    max_total_mb: float | None
    output_dir: Path
    player_dir: Path
    filename_template: str
    source: str | None  # None = auto-detect from playlist_url


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"config file not found: {path} (copy config.example.yaml to get started)"
        )
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    raw: dict[str, Any] = _expand_env(loaded)

    playlist_url = raw.get("playlist_url") or ""
    if not playlist_url.startswith(("http://", "https://")):
        raise ValueError("config: 'playlist_url' must be a Yandex Music playlist URL")

    token = raw.get("token") or os.environ.get("YM_TOKEN", "")
    if not token:
        raise ValueError(
            "config: no token — set 'token' in the config or the YM_TOKEN env var"
        )

    quality = str(raw.get("quality", "lossless")).lower()
    if quality not in VALID_QUALITIES:
        raise ValueError(
            f"config: 'quality' must be one of {VALID_QUALITIES}, got {quality!r}"
        )

    max_tracks = raw.get("max_tracks")
    if max_tracks is not None:
        max_tracks = int(max_tracks)
        if max_tracks < 1:
            raise ValueError("config: 'max_tracks' must be >= 1")

    max_total_mb = raw.get("max_total_mb")
    if max_total_mb is not None:
        max_total_mb = float(max_total_mb)
        if max_total_mb <= 0:
            raise ValueError("config: 'max_total_mb' must be > 0")

    base = path.parent
    output_dir = Path(raw.get("output_dir", "./music"))
    if not output_dir.is_absolute():
        output_dir = (base / output_dir).resolve()
    player_dir = Path(raw.get("player_dir") or "")
    if not str(raw.get("player_dir") or ""):
        raise ValueError("config: 'player_dir' (mounted player path) is required")

    template = raw.get("filename_template", "{position:0{width}d}-{name}.{ext}")
    for field in ("position", "name", "ext"):
        if f"{{{field}" not in template:
            raise ValueError(
                f"config: 'filename_template' must contain {{{field}}}"
            )

    source = raw.get("source")
    if source is not None:
        source = str(source).lower()
        if source not in AVAILABLE_SOURCES:
            raise ValueError(
                f"config: 'source' must be one of {AVAILABLE_SOURCES}, "
                f"got {source!r} (or omit it to auto-detect)"
            )

    return Config(
        playlist_url=playlist_url,
        token=token,
        quality=quality,
        max_tracks=max_tracks,
        max_total_mb=max_total_mb,
        output_dir=output_dir,
        player_dir=player_dir.expanduser(),
        filename_template=template,
        source=source,
    )
