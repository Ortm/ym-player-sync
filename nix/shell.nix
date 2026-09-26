{
  mkShell,
  nixfmt-rfc-style,
  python3,
  uv,
}:

mkShell {
  packages = [
    nixfmt-rfc-style
    python3
    uv
  ];
}
