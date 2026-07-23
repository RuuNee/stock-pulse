"""JSON writing helpers.

Every file the pipeline emits goes through :func:`write_json` so the schema
rules in md파일/02-데이터스키마.md (UTF-8, no NaN, atomic writes) hold globally.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from ..config import CACHE_DIR, ROOT
from . import log


def _clean(obj: Any) -> Any:
    """Replace NaN/Infinity with None — they are not valid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, 6)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    # numpy scalars and pandas timestamps
    if hasattr(obj, "item"):
        try:
            return _clean(obj.item())
        except Exception:  # pragma: no cover - defensive
            return str(obj)
    return obj


def write_json(path: Path, payload: Any, *, quiet: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(_clean(payload), ensure_ascii=False, separators=(",", ":"))
    # Atomic write so a crashed run never leaves a half-written file that the
    # site would fail to parse.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    if not quiet:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        log.ok(f"wrote {shown} ({len(data) / 1024:.0f}KB)")
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warn(f"failed to read {path.name}: {exc}")
        return default


# --------------------------------------------------------------------------
# Disk cache — keeps slow listings (NASDAQ takes ~9s) out of the hot path.
# --------------------------------------------------------------------------
def cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def cache_get(key: str, max_age_sec: int) -> Any:
    p = cache_path(key)
    if not p.exists():
        return None
    import time
    if time.time() - p.stat().st_mtime > max_age_sec:
        return None
    return read_json(p)


def cache_set(key: str, payload: Any) -> None:
    write_json(cache_path(key), payload, quiet=True)
