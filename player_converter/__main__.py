if __package__ in (None, ""):
    # Allow running as a file: `python player_converter/__main__.py`
    # (`uv run player_converter` does this — it executes __main__.py
    # without package context, so the relative import below fails.)
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from player_converter.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
