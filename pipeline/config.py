"""Central configuration for the Stock Pulse pipeline.

Everything tunable lives here: the tracked universe, news feeds, event
thresholds and LLM budget. See md파일/01-데이터소스.md for the verification
results behind the feed list.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")

SITE_URL = os.getenv("SITE_URL", "https://stock-pulse.vercel.app")

# --------------------------------------------------------------------------
# Universe
#
# (code, display name, exchange, [aliases used for news matching])
# Aliases matter a lot for Korean news: articles say "삼전" or "하이닉스"
# far more often than the full registered name.
# --------------------------------------------------------------------------
KR_UNIVERSE: list[tuple[str, str, str, list[str]]] = [
    ("005930", "삼성전자", "KOSPI", ["삼전"]),
    ("000660", "SK하이닉스", "KOSPI", ["하이닉스"]),
    ("373220", "LG에너지솔루션", "KOSPI", ["LG엔솔", "엘지에너지솔루션"]),
    ("207940", "삼성바이오로직스", "KOSPI", ["삼바", "삼성바이오"]),
    ("005380", "현대차", "KOSPI", ["현대자동차"]),
    ("000270", "기아", "KOSPI", ["기아차"]),
    ("068270", "셀트리온", "KOSPI", []),
    ("035420", "NAVER", "KOSPI", ["네이버"]),
    ("035720", "카카오", "KOSPI", []),
    ("005490", "POSCO홀딩스", "KOSPI", ["포스코홀딩스", "포스코"]),
    ("105560", "KB금융", "KOSPI", ["국민은행", "KB금융지주"]),
    ("055550", "신한지주", "KOSPI", ["신한금융", "신한은행"]),
    ("006400", "삼성SDI", "KOSPI", []),
    ("051910", "LG화학", "KOSPI", []),
    ("012330", "현대모비스", "KOSPI", ["모비스"]),
    ("329180", "HD현대중공업", "KOSPI", ["현대중공업"]),
    ("012450", "한화에어로스페이스", "KOSPI", ["한화에어로"]),
    ("034020", "두산에너빌리티", "KOSPI", ["두산에너빌"]),
    ("352820", "하이브", "KOSPI", ["HYBE"]),
    ("259960", "크래프톤", "KOSPI", []),
    ("323410", "카카오뱅크", "KOSPI", ["카뱅"]),
    ("042700", "한미반도체", "KOSPI", []),
    ("196170", "알테오젠", "KOSDAQ", []),
    ("247540", "에코프로비엠", "KOSDAQ", ["에코프로BM"]),
    ("028300", "HLB", "KOSDAQ", ["에이치엘비"]),
    ("058470", "리노공업", "KOSDAQ", []),
    ("035900", "JYP Ent.", "KOSDAQ", ["JYP", "제이와이피"]),
    ("041510", "에스엠", "KOSDAQ", ["SM엔터", "SM엔터테인먼트"]),
    ("263750", "펄어비스", "KOSDAQ", []),
    ("039030", "이오테크닉스", "KOSDAQ", []),
]

US_UNIVERSE: list[tuple[str, str, str, list[str]]] = [
    ("AAPL", "Apple", "NASDAQ", ["애플"]),
    ("MSFT", "Microsoft", "NASDAQ", ["마이크로소프트"]),
    ("NVDA", "NVIDIA", "NASDAQ", ["엔비디아"]),
    ("GOOGL", "Alphabet", "NASDAQ", ["구글", "알파벳"]),
    ("AMZN", "Amazon", "NASDAQ", ["아마존"]),
    ("META", "Meta Platforms", "NASDAQ", ["메타"]),
    ("TSLA", "Tesla", "NASDAQ", ["테슬라"]),
    ("AVGO", "Broadcom", "NASDAQ", ["브로드컴"]),
    ("AMD", "AMD", "NASDAQ", ["에이엠디"]),
    ("NFLX", "Netflix", "NASDAQ", ["넷플릭스"]),
    ("JPM", "JPMorgan Chase", "NYSE", ["JP모건"]),
    ("V", "Visa", "NYSE", ["비자"]),
    ("MA", "Mastercard", "NYSE", ["마스터카드"]),
    ("UNH", "UnitedHealth", "NYSE", []),
    ("XOM", "Exxon Mobil", "NYSE", ["엑슨모빌"]),
    ("WMT", "Walmart", "NYSE", ["월마트"]),
    ("COST", "Costco", "NASDAQ", ["코스트코"]),
    ("LLY", "Eli Lilly", "NYSE", ["일라이릴리"]),
    ("ORCL", "Oracle", "NYSE", ["오라클"]),
    ("CRM", "Salesforce", "NYSE", ["세일즈포스"]),
    ("ADBE", "Adobe", "NASDAQ", ["어도비"]),
    ("INTC", "Intel", "NASDAQ", ["인텔"]),
    ("MU", "Micron", "NASDAQ", ["마이크론"]),
    ("TSM", "TSMC", "NYSE", ["TSMC", "대만반도체"]),
    ("ASML", "ASML", "NASDAQ", ["ASML"]),
    ("PLTR", "Palantir", "NASDAQ", ["팔란티어"]),
    ("COIN", "Coinbase", "NASDAQ", ["코인베이스"]),
    ("SMCI", "Super Micro", "NASDAQ", ["슈퍼마이크로"]),
    ("QQQ", "Invesco QQQ ETF", "NASDAQ", ["나스닥100 ETF"]),
    ("SPY", "SPDR S&P 500 ETF", "NYSE", ["S&P500 ETF"]),
]

# --------------------------------------------------------------------------
# Macro symbols  (all verified against FinanceDataReader on 2026-07-22)
#
# key, display name, market bucket, group, unit, beginner note
# --------------------------------------------------------------------------
MACRO_SYMBOLS: list[dict] = [
    {"key": "KS11", "name": "코스피", "market": "KR", "group": "index", "unit": "pt",
     "note": "한국 대표 기업들을 모아 만든 평균 성적표입니다."},
    {"key": "KQ11", "name": "코스닥", "market": "KR", "group": "index", "unit": "pt",
     "note": "중소·벤처기업 중심 시장입니다. 코스피보다 출렁임이 큽니다."},
    {"key": "US500", "name": "S&P 500", "market": "US", "group": "index", "unit": "pt",
     "note": "미국 대표 기업 500곳의 평균 성적표. 세계 증시의 기준입니다."},
    {"key": "IXIC", "name": "나스닥", "market": "US", "group": "index", "unit": "pt",
     "note": "기술주가 많이 모인 시장입니다. 금리에 민감하게 반응합니다."},
    {"key": "DJI", "name": "다우존스", "market": "US", "group": "index", "unit": "pt",
     "note": "미국 전통 대형 기업 30곳을 묶은 지수입니다."},
    {"key": "VIX", "name": "VIX 공포지수", "market": "US", "group": "index", "unit": "pt",
     "note": "투자자들의 불안 정도. 20을 넘으면 시장이 겁먹었다는 뜻입니다."},
    {"key": "USD/KRW", "name": "원달러 환율", "market": "KR", "group": "fx", "unit": "원",
     "note": "1달러를 사는 데 드는 원화. 오르면 외국인이 한국 주식을 팔 유인이 커집니다."},
    {"key": "DX-Y.NYB", "name": "달러인덱스", "market": "GLOBAL", "group": "fx", "unit": "pt",
     "note": "달러가 다른 통화들 대비 얼마나 센지. 오르면 신흥국 주식에 불리합니다."},
    {"key": "^TNX", "name": "미 10년물 금리", "market": "US", "group": "rate", "unit": "%",
     "note": "미국 정부가 10년간 돈 빌릴 때 내는 이자. 오르면 주식 매력이 줄어듭니다."},
    {"key": "CL=F", "name": "WTI 유가", "market": "GLOBAL", "group": "commodity", "unit": "$",
     "note": "국제 유가. 오르면 물가가 오르고 항공·운송업에 부담이 됩니다."},
    {"key": "GC=F", "name": "금", "market": "GLOBAL", "group": "commodity", "unit": "$",
     "note": "대표적인 안전자산. 불안할 때 값이 오릅니다."},
    {"key": "BTC/KRW", "name": "비트코인", "market": "GLOBAL", "group": "crypto", "unit": "원",
     "note": "위험자산 선호도를 보여주는 참고 지표입니다."},
]

# --------------------------------------------------------------------------
# News feeds  (verified 2026-07-22 — dead feeds already removed)
#
# key: (display name, url, market, weight)
# --------------------------------------------------------------------------
FEEDS: dict[str, dict] = {
    # ---- 국장 ----
    "yna_market": {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/market.xml",
                   "market": "KR", "weight": 1.0},
    "yna_economy": {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/economy.xml",
                    "market": "KR", "weight": 0.95},
    "hankyung_finance": {"name": "한국경제", "url": "https://www.hankyung.com/feed/finance",
                         "market": "KR", "weight": 0.9},
    "hankyung_economy": {"name": "한국경제", "url": "https://www.hankyung.com/feed/economy",
                         "market": "KR", "weight": 0.85},
    "mk_stock": {"name": "매일경제", "url": "https://www.mk.co.kr/rss/50200011/",
                 "market": "KR", "weight": 0.9},
    "mk_economy": {"name": "매일경제", "url": "https://www.mk.co.kr/rss/30100041/",
                   "market": "KR", "weight": 0.85},
    "chosunbiz": {"name": "조선비즈",
                  "url": "https://biz.chosun.com/arc/outboundfeeds/rss/category/stock/?outputType=xml",
                  "market": "KR", "weight": 0.85},
    "infostock": {"name": "인포스탁데일리",
                  "url": "https://www.infostockdaily.co.kr/rss/allArticle.xml",
                  "market": "KR", "weight": 0.7},
    "khan_economy": {"name": "경향신문",
                     "url": "https://www.khan.co.kr/rss/rssdata/economy_news.xml",
                     "market": "KR", "weight": 0.7},
    "hani_economy": {"name": "한겨레", "url": "https://www.hani.co.kr/rss/economy/",
                     "market": "KR", "weight": 0.7},
    # ---- 미장 ----
    "wsj_markets": {"name": "WSJ",
                    "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
                    "market": "US", "weight": 1.0},
    "bloomberg_markets": {"name": "Bloomberg",
                          "url": "https://feeds.bloomberg.com/markets/news.rss",
                          "market": "US", "weight": 1.0},
    "fed_press": {"name": "연준(Fed)",
                  "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
                  "market": "US", "weight": 1.0},
    "cnbc_markets": {"name": "CNBC",
                     "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
                     "market": "US", "weight": 0.9},
    "cnbc_top": {"name": "CNBC",
                 "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
                 "market": "US", "weight": 0.85},
    "ft_markets": {"name": "Financial Times", "url": "https://www.ft.com/markets?format=rss",
                   "market": "US", "weight": 0.9},
    "yahoo_finance": {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex",
                      "market": "US", "weight": 0.85},
    "marketwatch": {"name": "MarketWatch",
                    "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
                    "market": "US", "weight": 0.85},
    "seeking_alpha": {"name": "Seeking Alpha", "url": "https://seekingalpha.com/market_currents.xml",
                      "market": "US", "weight": 0.75},
    "investing_com": {"name": "Investing.com", "url": "https://www.investing.com/rss/news_25.rss",
                      "market": "US", "weight": 0.7},
    "nasdaq_markets": {"name": "Nasdaq",
                       "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
                       "market": "US", "weight": 0.7},
}

# Per-ticker news templates. See md파일/01-데이터소스.md §3.
YAHOO_TICKER_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
GOOGLE_NEWS_DELAY_SEC = 1.5  # Google News 429s if hit too fast

USER_AGENT = "Mozilla/5.0 (compatible; StockPulse/1.0; +https://github.com/RuuNee/stock-pulse)"
HTTP_TIMEOUT = 15

# --------------------------------------------------------------------------
# Analysis thresholds
# --------------------------------------------------------------------------
HISTORY_YEARS = 2          # how much OHLCV history to keep per ticker
EVENT_LOOKBACK_DAYS = 400  # how far back to detect events

EVENT_ZSCORE = 1.8         # |return| in std-devs of trailing 60d returns
EVENT_ABS_PCT = 3.5        # or absolute % move (whichever triggers first)
EVENT_VOLUME_RATIO = 2.5   # volume vs 20d average
EVENT_GAP_PCT = 2.5        # open vs previous close

EVENT_SEVERITY_BANDS = [(3.5, 1), (5.0, 2), (8.0, 3)]  # (|pct| >= x, severity)

NEWS_KEEP_DAYS = 3         # how much of the general feed to publish
NEWS_MAX_ITEMS = 400
TICKER_NEWS_DAYS = 400     # per-ticker news retained for event matching
RECENT_NEWS_PER_TICKER = 10

# Keywords that raise a headline's importance score.
IMPORTANT_KEYWORDS_KR = [
    "금리", "기준금리", "FOMC", "연준", "한국은행", "환율", "관세", "무역",
    "실적", "영업이익", "어닝", "공시", "인수", "합병", "증자", "감자",
    "상한가", "하한가", "급등", "급락", "폭락", "신고가", "신저가",
    "반도체", "수출", "무역수지", "인플레이션", "물가", "경기침체", "공매도",
]
IMPORTANT_KEYWORDS_EN = [
    "fed", "fomc", "rate", "inflation", "cpi", "jobs", "earnings", "guidance",
    "tariff", "merger", "acquisition", "downgrade", "upgrade", "surge", "plunge",
    "recession", "yield", "treasury", "chip", "semiconductor", "sanction",
]

POSITIVE_WORDS_KR = ["상승", "급등", "호조", "개선", "수주", "흑자", "신고가", "돌파", "기대", "호실적", "성장"]
NEGATIVE_WORDS_KR = ["하락", "급락", "폭락", "부진", "악화", "적자", "신저가", "우려", "리스크", "감소", "쇼크"]
POSITIVE_WORDS_EN = ["surge", "rally", "beat", "jump", "gain", "record high", "upgrade", "strong", "soar"]
NEGATIVE_WORDS_EN = ["plunge", "slump", "miss", "drop", "fall", "downgrade", "weak", "cut", "slide", "tumble"]

# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
LLM_MODEL = "claude-haiku-4-5-20251001"
LLM_MAX_EVENTS_PER_RUN = 40   # cost guard — raise for richer coverage
LLM_MAX_TOKENS = 900
LLM_ENABLED = True            # falls back to rules automatically without a key


def anthropic_key() -> str | None:
    return os.getenv("ANTHROPIC_API_KEY") or None


def telegram_token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN") or None


def telegram_chat_id() -> str | None:
    return os.getenv("TELEGRAM_CHAT_ID") or None


def universe(market: str) -> list[tuple[str, str, str, list[str]]]:
    return KR_UNIVERSE if market.upper() == "KR" else US_UNIVERSE


def all_universe() -> list[dict]:
    """Flattened universe with market tags, used by most modules."""
    out: list[dict] = []
    for market, rows in (("KR", KR_UNIVERSE), ("US", US_UNIVERSE)):
        for code, name, exchange, aliases in rows:
            out.append({
                "code": code,
                "name": name,
                "market": market,
                "exchange": exchange,
                "aliases": aliases,
                "currency": "KRW" if market == "KR" else "USD",
            })
    return out
