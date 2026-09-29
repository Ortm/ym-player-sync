{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "music-sync";
  # Keep in sync with music_sync/__init__.py.
  version = (lib.importTOML ../pyproject.toml).project.version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../music_sync
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

  pythonImportsCheck = [ "music_sync" ];

  meta = {
    description = "Download a Yandex Music playlist and mirror it onto a USB music player";
    homepage = "https://github.com/Ortm/music-sync";
    changelog = "https://github.com/Ortm/music-sync/commits/main";
    license = lib.licenses.mit;
    mainProgram = "music-sync";
    platforms = lib.platforms.unix;
  };
}
