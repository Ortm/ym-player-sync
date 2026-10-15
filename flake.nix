{
  description = "Sync a Yandex Music playlist onto a USB music player";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
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
                ym-player-sync init | grep -qF "config/config.yaml"
                test -f config/config.yaml
                grep -qF "playlist_url" config/config.yaml
                # a second run must refuse instead of clobbering the config
                if ym-player-sync init; then
                  echo "init overwrote an existing config" >&2
                  exit 1
                fi
                touch $out
              '';
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
