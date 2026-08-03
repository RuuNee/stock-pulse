"""Technical indicators aligned 1:1 with the OHLCV rows the site receives.

계산 자체는 `technical.py` 에 있다 — 차트에 그릴 시계열과 신호 판정이 같은
공식을 써야 "차트에 그려진 선"과 "분석 카드가 말하는 근거"가 어긋나지 않는다.
이 모듈은 파이프라인이 부르던 이름을 유지하는 얇은 껍데기다.
"""

from __future__ import annotations

import pandas as pd

from .technical import rsi, series


def compute(df: pd.DataFrame) -> dict[str, list[float | None]]:
    return series(df)


__all__ = ["compute", "rsi"]
