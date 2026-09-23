# Home Manager module for player-converter.
#
# Usage in home.nix:
#   {
#     inputs.player-converter.url = "github:Ortm/player_coverter";
#     # ...
#     nixpkgs.overlays = [ inputs.player-converter.overlays.default ];
#     imports = [ inputs.player-converter.homeManagerModules.default ];
#     programs.player-converter = {
#       enable = true;
#       playlistUrl = "https://music.yandex.ru/users/<login>/playlists/<kind>";
#       playerDir = "/run/media/${config.home.username}/PLAYER/Music";
#       quality = "lossless";
#       tokenFile = "/run/agenix/ym-token";  # file with `YM_TOKEN=...`
#       schedule = "daily";                   # optional systemd user timer
#     };
#   }
{ config, lib, pkgs, ... }:
let
  cfg = config.programs.player-converter;
  yamlFormat = pkgs.formats.yaml { };
  settings = lib.filterAttrs (_: v: v != null) (
    {
      playlist_url = cfg.playlistUrl;
      token = cfg.token;
      quality = cfg.quality;
      max_tracks = cfg.maxTracks;
      max_total_mb = cfg.maxTotalMb;
      source = cfg.source;
      output_dir = cfg.outputDir;
      player_dir = cfg.playerDir;
      filename_template = cfg.filenameTemplate;
    }
    // cfg.extraSettings
  );
  configFile = yamlFormat.generate "player-converter-config.yaml" settings;
in
{
  options.programs.player-converter = {
    enable = lib.mkEnableOption "player-converter, Yandex Music playlist to USB player sync";

    package = lib.mkPackageOption pkgs "player-converter" { };

    playlistUrl = lib.mkOption {
      type = lib.types.str;
      example = "https://music.yandex.ru/users/<login>/playlists/<kind>";
      description = "Yandex Music playlist URL to sync.";
    };

    # Keep the secret out of the Nix store: default reads it from the
    # environment, and the systemd service can load it via tokenFile.
    token = lib.mkOption {
      type = lib.types.str;
      default = "\${YM_TOKEN}";
      description = "Yandex Music OAuth token. Use a literal token only for throwaway setups.";
    };

    tokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      example = "/run/agenix/ym-token";
      description = "EnvironmentFile for the sync service, containing `YM_TOKEN=...` (agenix/sops-nix friendly).";
    };

    quality = lib.mkOption {
      type = lib.types.enum [
        "lossless"
        "high"
        "low"
      ];
      default = "lossless";
      description = "Download tier: lossless (FLAC), high (MP3 320), low (smallest variant).";
    };

    source = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "yandex" ]);
      default = null;
      description = "Music source. Null auto-detects from the playlist URL.";
    };

    maxTracks = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "Sync only the first N playlist tracks.";
    };

    maxTotalMb = lib.mkOption {
      type = lib.types.nullOr lib.types.number;
      default = null;
      description = "Cap on estimated total download size in MB.";
    };

    outputDir = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/Music/player-converter";
      description = "Local cache directory for downloads and sync state.";
    };

    playerDir = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/run/media/vix/PLAYER/Music";
      description = "Mounted player path (must exist when syncing).";
    };

    filenameTemplate = lib.mkOption {
      type = lib.types.str;
      default = "{position:0{width}d}-{title} - {artists}.{ext}";
      description = "Output filename template.";
    };

    extraSettings = lib.mkOption {
      type = yamlFormat.type;
      default = { };
      description = "Extra config.yaml keys, merged over the typed options (forward compatibility).";
    };

    schedule = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "daily";
      description = "systemd OnCalendar schedule for automatic syncs. Null disables the timer.";
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      assertions = [
        {
          assertion = cfg.playlistUrl != "";
          message = "programs.player-converter.playlistUrl must be set.";
        }
        {
          assertion = cfg.playerDir != null;
          message = "programs.player-converter.playerDir must be set.";
        }
      ];

      xdg.configFile."player-converter/config.yaml".source = configFile;
    }

    (lib.mkIf (cfg.schedule != null) {
      systemd.user.services.player-converter-sync = {
        Unit.Description = "Sync Yandex Music playlist to USB player";
        Service = {
          Type = "oneshot";
          ExecStart = "${pkgs.bash}/bin/bash -c '${cfg.package}/bin/player-converter -c ${configFile} download && ${cfg.package}/bin/player-converter -c ${configFile} sync'";
        }
        // lib.optionalAttrs (cfg.tokenFile != null) {
          EnvironmentFile = cfg.tokenFile;
        };
      };

      systemd.user.timers.player-converter-sync = {
        Unit.Description = "Sync Yandex Music playlist to USB player (timer)";
        Timer = {
          OnCalendar = cfg.schedule;
          Persistent = true;
        };
        Install.WantedBy = [ "timers.target" ];
      };
    })
  ]);
}
