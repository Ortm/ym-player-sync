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
        music-sync = nixpkgs.legacyPackages.${system}.callPackage ./nix/package.nix { };
        default = self.packages.${system}.music-sync;
      });

      overlays.default = final: _: {
        music-sync = final.callPackage ./nix/package.nix { };
      };

      homeManagerModules = {
        default = import ./nix/module.nix;
        music-sync = self.homeManagerModules.default;
      };

      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.callPackage ./nix/shell.nix { };
      });

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          package = self.packages.${system}.music-sync;
        in
        {
          inherit package;

          cli =
            pkgs.runCommand "music-sync-cli-check"
              {
                inherit (package) version;
                nativeBuildInputs = [ package ];
              }
              ''
                export HOME=$PWD
                music-sync --version | grep -qF "music-sync $version"
                music-sync --help | grep -qF "sync"
                touch $out
              '';
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-rfc-style);

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.music-sync;
        };
      });
    };
}
