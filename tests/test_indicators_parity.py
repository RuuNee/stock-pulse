"""차트 지표 — 파이썬 구현이 고정 픽스처에서 벗어나지 않는지 본다.

지표 계산은 2026-08-20 에 브라우저로 옮겼다 (11개 시계열이 종목 파일의 절반을
차지해서 `.git` 증식의 주범이었다). 그래서 이제 같은 수식이 두 곳에 있다:

- `pipeline/analyze/technical.series()` — 서버 판정(`analysis`)의 근거
- `web/src/lib/indicators.ts` — 차트에 실제로 그려지는 선

둘이 갈라지면 "차트에 그려진 선"과 "분석 카드가 말하는 근거"가 조용히 어긋난다.
종목 JSON 에서 `indicators` 를 뺐으니 실데이터로 대조할 수도 없다. 그래서 고정
픽스처를 두고 **양쪽에서 각각** 검사한다 — 이 파일이 파이썬 쪽, 웹 CI 의
`npm run check-indicators`(`web/scripts/check-indicators.mjs`)가 TS 쪽이다.

수식을 고칠 일이 생기면 양쪽 구현과 픽스처를 같은 커밋에서 갱신할 것.
픽스처 재생성은 `tests/fixtures/README.md` 참고.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.analyze import technical

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "indicators_parity.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


def test_series_matches_fixture(fixture):
    got = technical.series(_frame(fixture["rows"]))

    for key, expected in fixture["expected"].items():
        assert key in got, f"{key} 시계열이 사라졌다 — 웹 구현도 같이 고쳤는지 확인"
        actual = got[key]
        assert len(actual) == len(expected), f"{key} 길이가 OHLCV 와 어긋난다"
        for i, (a, b) in enumerate(zip(actual, expected)):
            assert (a is None) == (b is None), f"{key}[{i}]: null 여부가 달라졌다"
            if a is not None:
                assert a == pytest.approx(b, abs=0.011), f"{key}[{i}]: {a} vs {b}"


def test_indicators_are_index_aligned_with_ohlcv(fixture):
    """웹은 `ind[key][startIdx + i]` 로 OHLCV 행과 인덱스를 맞춰 읽는다."""
    rows = fixture["rows"]
    got = technical.series(_frame(rows))
    for key, values in got.items():
        assert len(values) == len(rows), f"{key} 가 OHLCV 행 수와 다르다"


def test_volma20_is_not_part_of_the_chart_contract(fixture):
    """차트가 안 쓰는 시계열을 픽스처에 되살리면 웹 검사가 실패한다."""
    assert "volMa20" not in fixture["expected"]
