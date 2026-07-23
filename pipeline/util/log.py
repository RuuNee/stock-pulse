"""Console logging that survives Windows terminals and GitHub Actions alike."""

from __future__ import annotations

import sys
import time

_START = time.time()
_LEVEL_TAG = {"info": "·", "ok": "✓", "warn": "!", "err": "✗", "step": "▸"}


def _emit(level: str, msg: str) -> None:
    elapsed = time.time() - _START
    line = f"[{elapsed:6.1f}s] {_LEVEL_TAG.get(level, '·')} {msg}"
    stream = sys.stderr if level == "err" else sys.stdout
    try:
        print(line, file=stream, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode(), file=stream, flush=True)


def info(msg: str) -> None:
    _emit("info", msg)


def ok(msg: str) -> None:
    _emit("ok", msg)


def warn(msg: str) -> None:
    _emit("warn", msg)


def err(msg: str) -> None:
    _emit("err", msg)


def step(msg: str) -> None:
    _emit("step", f"\n{msg}")
