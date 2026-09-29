if __package__ in (None, ""):
    # Allow running as a file: `python music_sync/__main__.py`
    # (`uv run music_sync` does this — it executes __main__.py
    # without package context, so the relative import below fails.)
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from music_sync.cli import main
else:
    from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
