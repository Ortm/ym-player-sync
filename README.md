# player-converter

Download a Yandex Music playlist via the API and mirror it onto a USB
music player: `001-Title - Artist.flac`, `002-…`, …

## Setup (uv)

```bash
uv sync
cp config.example.yaml config.yaml   # then fill in playlist_url, token, player_dir
export YM_TOKEN=...                   # or put the token in config.yaml
```

You need a Yandex Music OAuth token. Keep `config.yaml` private
(`chmod 600 config.yaml`, git-ignored) — it carries your token.

## Usage

```bash
uv run player-converter info                 # check token + playlist summary
uv run player-converter download --dry-run   # preview stage 1, change nothing
uv run player-converter download             # stage 1: fetch playlist into the cache
uv run player-converter sync --dry-run       # preview stage 2, change nothing
uv run player-converter sync                 # stage 2: mirror cache onto player (offline)
```

Or install it once (`uv tool install .`) and use `player-converter` directly.

## Setup (Nix / Home Manager)

```bash
nix run . -- info          # build & run straight from the flake
nix profile install .      # or install it, or use the overlay
```

Home Manager — add the flake as an input, then:

```nix
inputs.player-converter.url = "github:Ortm/player_coverter";
# ...
nixpkgs.overlays = [ inputs.player-converter.overlays.default ];
imports = [ inputs.player-converter.homeManagerModules.default ];

programs.player-converter = {
  enable = true;
  playlistUrl = "https://music.yandex.ru/users/<login>/playlists/<kind>";
  playerDir = "/run/media/vix/PLAYER/Music";
  quality = "lossless";
  tokenFile = "/run/agenix/ym-token";   # file holding the token
  schedule = "daily";                   # optional systemd user timer
};
```

This writes `~/.config/player-converter/config.yaml`, installs the package,
and keeps the token out of the Nix store (it is read from `tokenFile` when
a command runs). With `schedule` set it also installs a
`player-converter` user service + timer that runs the `download` and
`sync` stages in order; the unit is skipped while `playerDir` is absent,
so an unplugged player never fails the timer. Every option is typed, and
anything the module does not model can be passed through `settings`.

## Config (`config.yaml`)

| Option | What it does |
|---|---|
| `playlist_url` | Playlist URL: `…/users/<login>/playlists/<kind>`, `…/users/<login>/tracks` ("Liked"), `…/playlists/<uid>.<uuid>` (share link) or `…/playlist/<uuid>` |
| `source` | Music source, `null` = auto-detect from URL (only `yandex` for now) |
| `token` | OAuth token (`${YM_TOKEN}` supported; `YM_TOKEN` env var is the fallback) |
| `token_file` | Path of a file holding the token — either the bare token or an `YM_TOKEN=...` line (systemd `EnvironmentFile` / agenix / sops-nix style). Read at startup, so secrets stay out of configs and the Nix store; used when `token`/`YM_TOKEN` are empty |
| `quality` | Download tier, requested from the API per track — files are kept **as downloaded, no transcoding**, except `.m4a`, which is converted to FLAC (many players can't play MP4 containers; for FLAC-in-MP4 sources this is lossless): `lossless` → best lossless (FLAC), `high` → 320 kbps MP3, `low` → smallest variant (takes least space); exact codec follows the server response |
| `max_tracks` | Only the first N playlist tracks (`null` = all); everything beyond N is deleted from cache and player |
| `workers` | Parallel downloads on the `download` stage, `1` = sequential (default `4`) |
| `max_total_mb` | Cap on estimated total download size; keeps every track that fits, always at least the first (`null` = no cap); tracks over budget are deleted from cache and player |
| `output_dir` | Local cache dir (downloads + sync state) |
| `player_dir` | Mounted player path — must exist (fails loudly if the player isn't plugged in) |
| `filename_template` | Naming, default `{position:0{width}d}-{title} - {artists}.{ext}` → `001-Title - Artist.flac` |

## How it works

`download` (needs network + token):

1. Playlist order is fetched, unavailable tracks skipped, `max_tracks` applied.
2. For each track the variant matching `quality` is picked; sizes are
   estimated from `bitrate × duration` and `max_total_mb` is applied.
3. The cache (`output_dir`) is mirrored:
   - a track already on disk **under a different name** (older naming
     scheme, artist-first order, a hand-copied file) is *renamed* to the
     current name — the audio bytes are never re-downloaded; matching
     strips the position prefix and ignores separator/punctuation/case
     and artist order, but not extra words (`Song (Live)` is a different
     track) or a different extension;
   - a file that exists only on the player is **recovered** into the cache
     (`[adopt]`) instead of being downloaded again;
   - position changes become cheap renames (`[renumber]`);
   - everything else managed is deleted — so lowering `max_tracks` /
     `max_total_mb` prunes the tracks that no longer fit the queue, and
     leftover `.part` files from interrupted downloads are cleaned up.

`sync` (offline — needs only the cache and the plugged-in player):

4. The player (`player_dir`) is mirrored **exactly**: files no longer in
   the queue are deleted **first** to free space, then new/changed files
   are copied over. Non-audio files on the player are left alone; hidden
   state lives in `output_dir/.player-converter-state.json`.

## Project structure

```
player_converter/
  cli.py            # argument parsing, `download` / `sync` / `info` commands
  config.py         # YAML loading + validation
  models.py         # Track, Variant, PlaylistInfo, DesiredTrack
  naming.py         # player-safe filenames + numbering template
  limits.py         # max_tracks / max_total_mb truncation
  matching.py       # find a track saved under a different filename
  audio.py          # m4a -> FLAC post-processing (imageio-ffmpeg/ffmpeg)
  sources/
    __init__.py     # PlaylistSource protocol, registry, detect_source()
    yandex.py       # Yandex Music implementation
  sync/
    cache.py        # download/rename/prune local cache (+ state file)
    player.py       # exact-mirror cache -> player
tests/              # network-free pytest suite (`uv run pytest`)
flake.nix           # inputs, packages, overlay, HM module, checks, formatter
nix/
  package.nix       # nixpkgs-style buildPythonApplication (runs the test suite)
  module.nix        # Home Manager module (config file + systemd timer)
  shell.nix         # dev shell (`nix develop`)
```

## Adding a new source

1. Subclass the `PlaylistSource` protocol in `sources/<name>.py`
   (`set_token`, `account_login`, `fetch_playlist`, `fetch_tracks`,
   `pick_variant`, `download`).
2. Register it in `AVAILABLE_SOURCES` / `get_source()` and extend
   `detect_source()` if the source is guessable from the URL.
3. Add tests. Nothing else changes — CLI, limits, naming, and both sync
   stages work against the protocol, not Yandex.

## Notes

- Tests: `uv run pytest` (80 tests, network-free). `nix flake check` builds
  the package, runs the same suite in the sandbox, and smoke-tests the CLI.
- License: MIT.
