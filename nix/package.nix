{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "ym-player-sync";
  # Keep in sync with ym_player_sync/__init__.py.
  version = (lib.importTOML ../pyproject.toml).project.version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../ym_player_sync
      ../tests
      ../pyproject.toml
      ../README.md
    ];
  };

  build-system = [ python3Packages.hatchling ];

  dependencies = with python3Packages; [
    imageio-ffmpeg
    pycryptodome
    pyyaml
    requests
  ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  pythonImportsCheck = [ "ym_player_sync" ];

  meta = {
    description = "Download a Yandex Music playlist and mirror it onto a USB music player";
    homepage = "https://github.com/Ortm/ym-player-sync";
    changelog = "https://github.com/Ortm/ym-player-sync/commits/main";
    license = lib.licenses.mit;
    mainProgram = "ym-player-sync";
    platforms = lib.platforms.unix;
  };
}
