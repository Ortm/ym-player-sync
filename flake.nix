{
  description = "Sync a Yandex Music playlist onto a USB music player";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  inputs.home-manager = {
    url = "github:nix-community/home-manager";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system: {
        ym-player-sync = nixpkgs.legacyPackages.${system}.callPackage ./nix/package.nix { };
        default = self.packages.${system}.ym-player-sync;
      });

      overlays.default = final: _: {
        ym-player-sync = final.callPackage ./nix/package.nix { };
      };

      homeManagerModules = {
        default = import ./nix/module.nix;
        ym-player-sync = self.homeManagerModules.default;
      };

      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.callPackage ./nix/shell.nix { };
      });

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          package = self.packages.${system}.ym-player-sync;

          # The Home Manager module is the "configure it with Nix settings"
          # surface — the one part `nix flake check` cannot exercise through
          # the CLI. Evaluate it with sample settings and assert the YAML
          # config.yaml it generates for them.
          hm = home-manager.lib.homeManagerConfiguration {
            inherit pkgs;
            modules = [
              self.homeManagerModules.default
              {
                home = {
                  username = "check";
                  homeDirectory = "/home/check";
                  stateVersion = "25.05";
                };
                programs.ym-player-sync = {
                  enable = true;
                  playlistUrl = "https://music.yandex.ru/users/check/tracks";
                  playerDir = "/mnt/player/favourite";
                  tokenFile = "/run/secrets/ym-token";
                  quality = "lossless";
                  embedCover = false;
                  maxTotalMb = 6000;
                  workers = 8;
                  schedule = "daily";
                };
              }
            ];
          };
          generatedConfig = hm.config.xdg.configFile."ym-player-sync/config.yaml".source;
          schedule = hm.config.systemd.user.timers.ym-player-sync.Timer.OnCalendar;
        in
        {
          inherit package;

          cli =
            pkgs.runCommand "ym-player-sync-cli-check"
              {
                inherit (package) version;
                nativeBuildInputs = [ package ];
              }
              ''
                export HOME=$PWD
                ym-player-sync --version | grep -qF "ym-player-sync $version"
                ym-player-sync --help | grep -qF "sync"
                ym-player-sync --help | grep -qF "init"
                ym-player-sync init | grep -qF "ym-player-sync/config.yaml"
                test -f "$HOME/.config/ym-player-sync/config.yaml"
                grep -qF "playlist_url" "$HOME/.config/ym-player-sync/config.yaml"
                # a second run must refuse instead of clobbering the config
                if ym-player-sync init; then
                  echo "init overwrote an existing config" >&2
                  exit 1
                fi
                touch $out
              '';

          module = nixpkgs.lib.optionalAttrs pkgs.stdenv.isLinux (
            pkgs.runCommand "ym-player-sync-module-check" { } ''
              set -eu
              cfg=${generatedConfig}
              grep -qF 'playlist_url: https://music.yandex.ru/users/check/tracks' "$cfg"
              grep -qF 'player_dir: /mnt/player/favourite' "$cfg"
              grep -qF 'token_file: /run/secrets/ym-token' "$cfg"
              grep -qF 'quality: lossless' "$cfg"
              grep -qF 'embed_cover: false' "$cfg"
              grep -qF 'max_total_mb: 6000' "$cfg"
              grep -qF 'workers: 8' "$cfg"
              # a literal token must never reach the Nix store
              grep -qF 'token: ''${YM_TOKEN}' "$cfg"
              # null options are left out, so the tool's own defaults apply
              if grep -qE '^max_tracks:|^source:' "$cfg"; then
                echo "a null option was written to the config" >&2
                exit 1
              fi
              # `schedule` wires the systemd user timer
              test "${schedule}" = "daily"
              touch $out
            ''
          );
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-rfc-style);

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.ym-player-sync;
        };
      });
    };
}
