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
        player-converter = nixpkgs.legacyPackages.${system}.callPackage ./nix/package.nix { };
        default = self.packages.${system}.player-converter;
      });

      overlays.default = final: _: {
        player-converter = final.callPackage ./nix/package.nix { };
      };

      homeManagerModules = {
        default = import ./nix/module.nix;
        player-converter = self.homeManagerModules.default;
      };

      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.callPackage ./nix/shell.nix { };
      });

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          package = self.packages.${system}.player-converter;
        in
        {
          inherit package;

          cli =
            pkgs.runCommand "player-converter-cli-check"
              {
                inherit (package) version;
                nativeBuildInputs = [ package ];
              }
              ''
                export HOME=$PWD
                player-converter --version | grep -qF "player-converter $version"
                player-converter --help | grep -qF "sync"
                touch $out
              '';
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-rfc-style);

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.player-converter;
        };
      });
    };
}
