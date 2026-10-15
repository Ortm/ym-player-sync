"""Text of the starter config `ym-player-sync init` writes out.

`init` writes it to the one location the tool reads —
``$XDG_CONFIG_HOME/ym-player-sync/config.yaml`` (~/.config by default) —
with every parameter present and commented. This constant is the single
source of that text.
"""

from __future__ import annotations

TEMPLATE = '''\
# ym-player-sync configuration — every available parameter, with its
# default. `ym-player-sync init` writes this file and never overwrites an
# existing one.
#
# This is the only place ym-player-sync reads its config from (a command
# can still be pointed elsewhere with --config <path>). ${VAR} in any
# value is expanded from the environment; an unset variable expands to
# nothing, so ${YM_TOKEN} stays empty until you export it.

# Playlist to mirror. Canonical form …/users/<login>/playlists/<kind>;
# also the Liked-tracks collection (…/users/<login>/tracks) and share
# links (…/playlists/<uid>.<uuid>).
playlist_url: "https://music.yandex.ru/users/<login>/playlists/<kind>"

# Music source. Null auto-detects from the playlist URL (only "yandex").
source: null

# Yandex Music token: either paste it into `token`, or point `token_file`
# at a file that holds it — a bare token or a YM_TOKEN=... line, which is
# what agenix/sops-nix write; the file keeps the secret out of this config
# and out of the Nix store. The YM_TOKEN environment variable is the last
# fallback. `token` wins when both are set.
token: ""
token_file: null
# token_file: "~/.config/sops-nix/secrets/ym-token"

# Download tier, requested from the API per track. Files are kept exactly
# as downloaded (no transcoding), except .m4a, which is repackaged to
# FLAC for players that cannot play MP4 containers:
#   lossless - best lossless variant (FLAC; needs Yandex Plus/Premium)
#   high     - 320 kbps MP3
#   low      - smallest variant
quality: lossless

# Write the track's metadata (artist, title, album, album artist, year,
# track/disc number) into every cached file: a player shows what is
# playing from the tags, not from the file name. Files that already carry
# them are not rewritten.
tags: true

# Embed the album cover into each file (needs `tags`). Best-effort: a
# failed fetch never fails the download, and the text tags are still
# written.
embed_cover: true

# Only the first N playlist tracks; null = no limit. Everything beyond N
# is deleted from the cache and the player.
max_tracks: null

# Cap the cache size in MB: estimates first, then a hard stop on the real
# bytes taken (the first track is always kept); null = no limit. Tracks
# over the budget are deleted from the cache and the player.
max_total_mb: 6000

# Local cache — downloads and the sync state live here. Relative paths
# are resolved against this file's directory.
output_dir: "~/Music/ym-player-sync"

# The mounted player; `ym-player-sync sync` mirrors the cache into its
# Music/ folder. It must be mounted when a sync runs.
player_dir: "/run/media/<user>/<label>/Music"

# Naming: {position} is the 1-based playlist position, zero-padded to
# {width} digits; {title}, {artists}, {ext} (the downloaded codec) and
# {name} ("Title - Artist") are also available. Must contain {position}
# and {ext}.
filename_template: "{position:0{width}d}-{title} - {artists}.{ext}"

# Parallel downloads on the `download` stage (1 = sequential).
workers: 4
'''
