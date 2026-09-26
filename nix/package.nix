{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "player-converter";
  # Keep in sync with player_converter/__init__.py.
  version = (lib.importTOML ../pyproject.toml).project.version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../player_converter
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

  pythonImportsCheck = [ "player_converter" ];

  meta = {
    description = "Download a Yandex Music playlist and mirror it onto a USB music player";
    homepage = "https://github.com/Ortm/player_coverter";
    changelog = "https://github.com/Ortm/player_coverter/blob/main/README.md";
    license = lib.licenses.mit;
    mainProgram = "player-converter";
    platforms = lib.platforms.unix;
  };
}
