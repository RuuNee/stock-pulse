"""문서-코드 드리프트 중 기계적으로 잡을 수 있는 것만 잡는다.

05-운영가이드는 월 점검 절차로 "죽은 피드 정리 → config.py + 01-데이터소스.md
동시 갱신"을 못박아 뒀는데, 정작 2026-07-28 에 `yna_market` 을 제거하면서 문서를
빠뜨렸다. 스펙 §14.2 드리프트 표가 길어진 것도 같은 이유다 — 사람 규칙은 샌다.
설정값 전부를 검증하려 들면 문서가 코드 복사본이 되므로, **운영자가 그 값을 보고
행동하는 것**(피드 목록, 튜닝 상수 기본값)만 고정한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipeline import config

DOCS = Path(__file__).resolve().parent.parent / "md파일"
SOURCES_DOC = DOCS / "01-데이터소스.md"


def rss_section() -> str:
    """01-데이터소스.md 의 '## 2. 뉴스 소스 — RSS' 절만."""
    text = SOURCES_DOC.read_text(encoding="utf-8")
    start = text.index("## 2. 뉴스 소스")
    end = text.index("## 3.", start)
    return text[start:end]


def documented_feed_keys() -> set[str]:
    """피드 표의 첫 칸(`| \\`key\\` |`)에 적힌 키."""
    return set(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", rss_section(), re.MULTILINE))


def test_every_live_feed_is_documented():
    missing = set(config.FEEDS) - documented_feed_keys()
    assert not missing, f"01-데이터소스.md 에 없는 피드: {sorted(missing)}"


def test_no_removed_feed_left_in_docs():
    """죽은 피드를 config 에서 빼고 문서에 남겨 두면 운영자가 살아있다고 믿는다."""
    stale = documented_feed_keys() - set(config.FEEDS)
    assert not stale, f"config 에 없는데 문서 표에 남은 피드: {sorted(stale)}"


@pytest.mark.parametrize("doc,pattern,value", [
    ("04-알림과스케줄.md", r"`LLM_MAX_EVENTS_PER_RUN`\(기본 (\d+)\)",
     lambda: config.LLM_MAX_EVENTS_PER_RUN),
    ("04-알림과스케줄.md", r"`TRANSLATE_MAX_ITEMS`\(기본 (\d+)\)",
     lambda: config.TRANSLATE_MAX_ITEMS),
    ("05-운영가이드.md", r"`GOOGLE_NEWS_DELAY_SEC` 상향 \(기본 ([\d.]+)초\)",
     lambda: config.GOOGLE_NEWS_DELAY_SEC),
    # 차트 분석 임계값 — 도움말 화면이 "RSI 70 이상이면 과매수"처럼 숫자를 그대로
    # 적어 두므로, 코드만 바꾸면 설명과 판정이 조용히 어긋난다.
    ("10-전체기술스펙.md", r"\| `TA_BREAKOUT_LOOKBACK` \| (\d+) \|",
     lambda: config.TA_BREAKOUT_LOOKBACK),
    ("10-전체기술스펙.md", r"\| `TA_RSI_OVERBOUGHT` / `TA_RSI_OVERSOLD` \| ([\d.]+) / [\d.]+ \|",
     lambda: config.TA_RSI_OVERBOUGHT),
    ("10-전체기술스펙.md", r"\| `TA_PULLBACK_BAND` \| ([\d.]+) \|",
     lambda: config.TA_PULLBACK_BAND),
    # 보관 기간은 운영자가 "언제까지 브리핑을 찾아볼 수 있나"를 판단하는 근거다.
    # 세 곳(스펙 표 · 스펙 §9.4 본문 · 운영가이드 조정표)에 숫자가 적혀 있다.
    ("10-전체기술스펙.md", r"\| `BRIEF_KEEP_DAYS` \| (\d+) \|",
     lambda: config.BRIEF_KEEP_DAYS),
    ("10-전체기술스펙.md", r"`BRIEF_KEEP_DAYS`\((\d+)일\)",
     lambda: config.BRIEF_KEEP_DAYS),
    ("05-운영가이드.md", r"`BRIEF_KEEP_DAYS` \(기본 (\d+)일\)",
     lambda: config.BRIEF_KEEP_DAYS),
])
def test_documented_defaults_match_config(doc, pattern, value):
    found = re.search(pattern, (DOCS / doc).read_text(encoding="utf-8"))
    assert found, f"{doc}: '{pattern}' 를 못 찾았습니다 (문구가 바뀌었으면 테스트도 갱신)"
    assert float(found.group(1)) == float(value()), \
        f"{doc}: 문서 {found.group(1)} vs 코드 {value()}"
