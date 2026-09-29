{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.ym-player-sync;

  yamlFormat = pkgs.formats.yaml { };

  settings =
    lib.filterAttrs (_: value: value != null) {
      playlist_url = cfg.playlistUrl;
      player_dir = cfg.playerDir;
      token = cfg.token;
      token_file = cfg.tokenFile;
      quality = cfg.quality;
      source = cfg.source;
      max_tracks = cfg.maxTracks;
      max_total_mb = cfg.maxTotalMb;
      workers = cfg.workers;
      output_dir = cfg.outputDir;
      filename_template = cfg.filenameTemplate;
    }
    // cfg.settings;

  configFile = yamlFormat.generate "ym-player-sync.yaml" settings;
in
{
  options.programs.ym-player-sync = {
    enable = lib.mkEnableOption "ym-player-sync, a Yandex Music playlist to USB player sync";

    package = lib.mkPackageOption pkgs "ym-player-sync" { };

    playlistUrl = lib.mkOption {
      type = lib.types.str;
      example = "https://music.yandex.ru/users/<login>/playlists/<kind>";
      description = "Yandex Music playlist URL to mirror.";
    };

    playerDir = lib.mkOption {
      type = lib.types.str;
      example = "/run/media/\${config.home.username}/PLAYER/Music";
      description = "Mount point of the USB player. It must be mounted when a sync runs.";
    };

    token = lib.mkOption {
      type = lib.types.str;
      default = "\${YM_TOKEN}";
      description = ''
        Yandex Music OAuth token, expanded from the environment when
        written as `''${VAR}`. Prefer {option}`tokenFile`: a literal token
        ends up in the world-readable Nix store.
      '';
    };

    tokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "/run/secrets/ym-token";
      description = ''
        Path to a file holding the token — either the bare token or an
        `YM_TOKEN=...` line (agenix/sops-nix friendly). The path is resolved
        when a command runs, so the file never enters the Nix store.
      '';
    };

    quality = lib.mkOption {
      type = lib.types.enum [
        "lossless"
        "high"
        "low"
      ];
      default = "lossless";
      description = "Download tier: lossless (FLAC), high (MP3 320 kbps), low (smallest variant).";
    };

    source = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "yandex" ]);
      default = null;
      description = "Music source. Null auto-detects from the playlist URL.";
    };

    maxTracks = lib.mkOption {
      type = lib.types.nullOr lib.types.ints.positive;
      default = null;
      description = "Mirror only the first N playlist tracks.";
    };

    maxTotalMb = lib.mkOption {
      type = lib.types.nullOr lib.types.number;
      default = null;
      description = "Cap on the estimated total download size in MB.";
    };

    workers = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4;
      description = "Parallel downloads on the download stage.";
    };

    outputDir = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/Music/ym-player-sync";
      description = "Local staging directory: downloaded files and sync state live here.";
    };

    filenameTemplate = lib.mkOption {
      type = lib.types.str;
      default = "{position:0{width}d}-{title} - {artists}.{ext}";
      description = "Output filename template.";
    };

    settings = lib.mkOption {
      inherit (yamlFormat) type;
      default = { };
      description = "Extra `config.yaml` keys, merged over the typed options.";
    };

    schedule = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "daily";
      description = ''
        `OnCalendar` schedule for a systemd user timer running
        `ym-player-sync download` followed by `ym-player-sync sync`.
        Null disables the timer.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = lib.optional (cfg.schedule != null) (
      lib.hm.assertions.assertPlatform "programs.ym-player-sync" pkgs lib.platforms.linux
    );

    home.packages = [ cfg.package ];

    xdg.configFile."ym-player-sync/config.yaml".source = configFile;

    systemd.user.services.ym-player-sync = lib.mkIf (cfg.schedule != null) {
      Unit = {
        Description = "Sync a Yandex Music playlist onto a USB player";
        Documentation = [ "https://github.com/Ortm/ym-player-sync" ];
        # Runs only while the player is plugged in; a missing player stays
        # a failure (never a silent partial sync).
        ConditionPathIsDirectory = cfg.playerDir;
      };

      Service = {
        Type = "oneshot";
        ExecStart = [
          "${lib.getExe cfg.package} --config ${configFile} download"
          "${lib.getExe cfg.package} --config ${configFile} sync"
        ];
      };
    };

    systemd.user.timers.ym-player-sync = lib.mkIf (cfg.schedule != null) {
      Unit = {
        Description = "Sync a Yandex Music playlist onto a USB player";
        Documentation = [ "https://github.com/Ortm/ym-player-sync" ];
      };

      Timer = {
        OnCalendar = cfg.schedule;
        Unit = "ym-player-sync.service";
      };

      Install.WantedBy = [ "timers.target" ];
    };
  };
}
