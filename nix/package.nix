# Nix packaging for player-converter (called with the flake's nixpkgs).
{
  lib,
  python3,
}:
python3.pkgs.buildPythonApplication {
  pname = "player-converter";
  version = "0.3.0";
  pyproject = true;

  src = ../.;

  build-system = [ python3.pkgs.hatchling ];

  dependencies = with python3.pkgs; [
    requests
    pyyaml
    pycryptodome
  ];

  # No test suite runs in the sandbox (tests are network-free but run via uv/pytest upstream).
  doCheck = false;

  meta = {
    description = "Download a Yandex Music playlist via API and mirror it onto a USB player";
    license = lib.licenses.mit;
    mainProgram = "player-converter";
  };
}
