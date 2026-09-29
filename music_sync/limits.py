"""Track-count / total-size limit helpers."""

from __future__ import annotations


def apply_limits(
    items: list,
    sizes: list[int],
    max_tracks: int | None,
    max_total_mb: float | None,
) -> list:
    """Truncate to max_tracks, then to max_total_mb of estimated bytes.

    The size cap keeps every item that fits; the first item is always
    kept even if it alone exceeds the cap (otherwise a tiny cap would
    silently sync nothing).
    """
    kept = list(items)
    kept_sizes = list(sizes)
    if max_tracks is not None:
        kept = kept[:max_tracks]
        kept_sizes = kept_sizes[:max_tracks]
    if max_total_mb is not None:
        cap = int(max_total_mb * 1_048_576)
        total = 0
        out: list = []
        for item, size in zip(kept, kept_sizes):
            if total + size <= cap or not out:
                out.append(item)
                total += size
            else:
                break
        kept = out
    return kept
