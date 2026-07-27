"""Central configuration for the Stock Pulse pipeline.

Everything tunable lives here: the tracked universe, news feeds, event
thresholds and LLM budget. See md파일/01-데이터소스.md for the verification
results behind the feed list.
"""

from __future__ import annotations

import os
import re
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
    # --- 대형주 확장 ---
    ("010120", "LS ELECTRIC", "KOSPI", ["LS일렉트릭", "LS일렉", "엘에스일렉트릭"]),
    ("066570", "LG전자", "KOSPI", ["엘지전자"]),
    ("003550", "LG", "KOSPI", ["LG지주", "엘지"]),
    ("017670", "SK텔레콤", "KOSPI", ["SKT", "에스케이텔레콤"]),
    ("030200", "KT", "KOSPI", ["케이티"]),
    ("034730", "SK", "KOSPI", ["SK지주", "에스케이"]),
    ("096770", "SK이노베이션", "KOSPI", ["SK이노", "에스케이이노베이션"]),
    ("032830", "삼성생명", "KOSPI", []),
    ("000810", "삼성화재", "KOSPI", []),
    ("086790", "하나금융지주", "KOSPI", ["하나금융", "하나은행"]),
    ("316140", "우리금융지주", "KOSPI", ["우리금융", "우리은행"]),
    ("138040", "메리츠금융지주", "KOSPI", ["메리츠금융", "메리츠"]),
    ("015760", "한국전력", "KOSPI", ["한전", "한국전력공사"]),
    ("028260", "삼성물산", "KOSPI", []),
    ("009150", "삼성전기", "KOSPI", []),
    ("010130", "고려아연", "KOSPI", []),
    ("009830", "한화솔루션", "KOSPI", []),
    ("051900", "LG생활건강", "KOSPI", ["엘지생활건강", "LG생건"]),
    ("090430", "아모레퍼시픽", "KOSPI", ["아모레"]),
    ("036570", "엔씨소프트", "KOSPI", ["엔씨", "NC소프트", "NC"]),
    ("251270", "넷마블", "KOSPI", []),
    ("009540", "HD한국조선해양", "KOSPI", ["한국조선해양"]),
    ("042660", "한화오션", "KOSPI", ["대우조선해양"]),
    ("010140", "삼성중공업", "KOSPI", []),
    ("003490", "대한항공", "KOSPI", []),
    ("000100", "유한양행", "KOSPI", []),
    ("326030", "SK바이오팜", "KOSPI", ["에스케이바이오팜"]),
    ("454910", "두산로보틱스", "KOSPI", ["두산로보"]),
    ("277810", "레인보우로보틱스", "KOSDAQ", ["레인보우"]),
    ("112040", "위메이드", "KOSDAQ", []),
    ("293490", "카카오게임즈", "KOSDAQ", ["카겜"]),
    ("357780", "솔브레인", "KOSDAQ", []),
    ("240810", "원익IPS", "KOSDAQ", []),
    ("086520", "에코프로", "KOSDAQ", []),
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
    # --- 대형주 확장 ---
    ("BAC", "Bank of America", "NYSE", ["뱅크오브아메리카", "BofA"]),
    ("KO", "Coca-Cola", "NYSE", ["코카콜라"]),
    ("PEP", "PepsiCo", "NASDAQ", ["펩시코", "펩시"]),
    ("MCD", "McDonald's", "NYSE", ["맥도날드"]),
    ("DIS", "Disney", "NYSE", ["디즈니", "월트디즈니"]),
    ("BA", "Boeing", "NYSE", ["보잉"]),
    ("PFE", "Pfizer", "NYSE", ["화이자"]),
    ("MRK", "Merck", "NYSE", ["머크"]),
    ("ABBV", "AbbVie", "NYSE", ["애브비"]),
    ("CVX", "Chevron", "NYSE", ["셰브론"]),
    ("NKE", "Nike", "NYSE", ["나이키"]),
    ("QCOM", "Qualcomm", "NASDAQ", ["퀄컴"]),
    ("TXN", "Texas Instruments", "NASDAQ", ["텍사스인스트루먼트"]),
    ("CSCO", "Cisco", "NASDAQ", ["시스코"]),
    ("IBM", "IBM", "NYSE", ["아이비엠"]),
    ("UBER", "Uber", "NYSE", ["우버"]),
    ("SHOP", "Shopify", "NYSE", ["쇼피파이"]),
    ("SNOW", "Snowflake", "NYSE", ["스노우플레이크"]),
    ("CRWD", "CrowdStrike", "NASDAQ", ["크라우드스트라이크"]),
    ("ARM", "Arm Holdings", "NASDAQ", ["암홀딩스"]),
    ("MSTR", "MicroStrategy", "NASDAQ", ["마이크로스트래티지", "스트래티지"]),
    ("DELL", "Dell", "NYSE", ["델테크놀로지스"]),
]

# --------------------------------------------------------------------------
# ETFs — tracked for price/chart/search only. Per-ticker news + event backfill
# are skipped (a basket's moves aren't explained by single-company news), so
# these are cheap to add in bulk. (code, name, "ETF", aliases)
# --------------------------------------------------------------------------
KR_ETF: list[tuple[str, str, str, list[str]]] = [
    ("069500", "KODEX 200", "ETF", ["코덱스200", "코덱스 200"]),
    ("102110", "TIGER 200", "ETF", ["타이거200"]),
    ("148020", "RISE 200", "ETF", []),
    ("278530", "KODEX 200TR", "ETF", []),
    ("277630", "TIGER 코스피", "ETF", ["코스피 ETF"]),
    ("229200", "KODEX 코스닥150", "ETF", ["코덱스 코스닥150"]),
    ("122630", "KODEX 레버리지", "ETF", ["코덱스 레버리지"]),
    ("114800", "KODEX 인버스", "ETF", ["코덱스 인버스"]),
    ("252670", "KODEX 200선물인버스2X", "ETF", ["곱버스"]),
    ("233740", "KODEX 코스닥150레버리지", "ETF", ["코스닥150 레버리지"]),
    ("360750", "TIGER 미국S&P500", "ETF", ["타이거 미국S&P500", "미국S&P500"]),
    ("379800", "KODEX 미국S&P500", "ETF", ["코덱스 미국S&P500"]),
    ("360200", "ACE 미국S&P500", "ETF", ["에이스 미국S&P500"]),
    ("133690", "TIGER 미국나스닥100", "ETF", ["타이거 나스닥100", "미국나스닥100"]),
    ("379810", "KODEX 미국나스닥100", "ETF", ["코덱스 나스닥"]),
    ("367380", "ACE 미국나스닥100", "ETF", []),
    ("225040", "TIGER 미국S&P500레버리지(합성 H)", "ETF", ["미국S&P500 레버리지"]),
    ("161510", "PLUS 고배당주", "ETF", ["아리랑 고배당주", "고배당 ETF"]),
    ("279530", "KODEX 고배당주", "ETF", []),
    ("211560", "TIGER 배당성장", "ETF", []),
    ("325020", "KODEX 배당가치", "ETF", []),
    ("458730", "TIGER 미국배당다우존스", "ETF", ["미국배당다우존스", "슈드 국내"]),
    ("446720", "SOL 미국배당다우존스", "ETF", []),
    ("441640", "KODEX 미국배당커버드콜액티브", "ETF", ["커버드콜"]),
    ("441680", "TIGER 미국나스닥100커버드콜(합성)", "ETF", ["나스닥 커버드콜"]),
    ("329200", "TIGER 리츠부동산인프라", "ETF", ["리츠 ETF"]),
    ("091160", "KODEX 반도체", "ETF", ["반도체 ETF"]),
    ("381180", "TIGER 미국필라델피아반도체나스닥", "ETF", ["미국반도체", "필라델피아반도체"]),
    ("305540", "TIGER 2차전지테마", "ETF", ["2차전지 ETF"]),
    ("462010", "TIGER 2차전지소재Fn", "ETF", []),
    ("305720", "KODEX 2차전지산업", "ETF", []),
    ("462330", "KODEX 2차전지산업레버리지", "ETF", []),
    ("449450", "PLUS K방산", "ETF", ["케이방산", "방산 ETF"]),
    ("463250", "TIGER K방산&우주", "ETF", ["방산 우주"]),
    ("0080G0", "KODEX 방산TOP10", "ETF", ["방산TOP10"]),
    ("421320", "PLUS 우주항공", "ETF", ["우주항공"]),
    ("0183J0", "TIGER 미국우주테크", "ETF", ["미국우주"]),
    ("434730", "HANARO 원자력iSelect", "ETF", ["원자력 ETF"]),
    ("490090", "TIGER 미국AI빅테크10", "ETF", ["AI ETF"]),
    ("472170", "TIGER 미국테크TOP10채권혼합", "ETF", ["미국 빅테크"]),
    ("314250", "KODEX 미국빅테크10(H)", "ETF", ["빅테크"]),
    ("456680", "TIGER 차이나전기차레버리지(합성)", "ETF", ["중국 전기차"]),
    ("453870", "TIGER 인도니프티50", "ETF", ["인도 ETF", "니프티"]),
    ("101280", "KODEX 일본TOPIX100", "ETF", ["일본 ETF"]),
    ("471230", "KODEX 국고채10년액티브", "ETF", ["국고채"]),
    ("305080", "TIGER 미국채10년선물", "ETF", ["미국채10년"]),
    ("476760", "ACE 미국30년국채액티브", "ETF", ["미국30년국채", "미국장기채"]),
    ("132030", "KODEX 골드선물(H)", "ETF", ["금 ETF", "골드"]),
    ("411060", "ACE KRX금현물", "ETF", ["금현물"]),
    ("261110", "TIGER 미국달러선물레버리지", "ETF", ["달러 ETF"]),
    ("143860", "TIGER 헬스케어", "ETF", ["헬스케어 ETF"]),
    ("091220", "TIGER 은행", "ETF", ["은행 ETF"]),
    ("091180", "KODEX 자동차", "ETF", ["자동차 ETF"]),
    ("228790", "TIGER 화장품", "ETF", ["화장품 ETF"]),
    ("228810", "TIGER 미디어컨텐츠", "ETF", ["엔터 ETF"]),
    ("244580", "KODEX 바이오", "ETF", ["바이오 ETF"]),
    ("300950", "KODEX 게임산업", "ETF", ["게임 ETF"]),
    ("494670", "TIGER 조선TOP10", "ETF", ["조선 ETF"]),
]

US_ETF: list[tuple[str, str, str, list[str]]] = [
    ("VOO", "Vanguard S&P 500 ETF", "ETF", ["뱅가드 S&P500"]),
    ("VTI", "Vanguard Total Market ETF", "ETF", ["뱅가드 토탈마켓"]),
    ("SOXX", "iShares Semiconductor ETF", "ETF", ["반도체 ETF", "필라델피아 반도체"]),
    ("SMH", "VanEck Semiconductor ETF", "ETF", ["반도체 ETF"]),
    ("ARKK", "ARK Innovation ETF", "ETF", ["아크 이노베이션", "돈나무"]),
    ("IWM", "iShares Russell 2000 ETF", "ETF", ["러셀2000 ETF"]),
    ("DIA", "SPDR Dow Jones ETF", "ETF", ["다우 ETF"]),
    ("SCHD", "Schwab US Dividend ETF", "ETF", ["슈드", "배당 ETF"]),
    ("TQQQ", "ProShares UltraPro QQQ", "ETF", ["나스닥100 3배"]),
    ("GLD", "SPDR Gold Shares", "ETF", ["금 ETF"]),
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
     "note": "S&P500 옵션으로 계산한 향후 30일 기대 변동성. 20 아래면 평온, 30 넘으면 시장이 겁먹은 상태예요."},
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
    # nasdaq_markets 제거: 응답이 자주 타임아웃(20s)됨 — 2026-07-23 실측. 99-스펙변경이력 참고.
}

# Per-ticker news templates. See md파일/01-데이터소스.md §3.
YAHOO_TICKER_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
GOOGLE_NEWS_KR = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
GOOGLE_NEWS_US = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_RSS = GOOGLE_NEWS_KR  # back-compat alias
GOOGLE_NEWS_DELAY_SEC = 1.2  # Google News 429s if hit too fast

# ⭐ Historical news backfill for chart events (R5). We only collect *recent*
# RSS, so events from months ago have no matched news on first run. For the top
# newsless events per ticker, run one date-scoped Google News query each.
EVENT_NEWS_BACKFILL = True
EVENT_BACKFILL_MAX_PER_TICKER = 6   # cap queries: 60 tickers × 6 × 1.2s ≈ 7min
EVENT_BACKFILL_MAX_AGE_DAYS = 200   # don't backfill ancient events

USER_AGENT = "Mozilla/5.0 (compatible; StockPulse/1.0; +https://github.com/RuuNee/stock-pulse)"
HTTP_TIMEOUT = 15

# --------------------------------------------------------------------------
# Analysis thresholds
# --------------------------------------------------------------------------
HISTORY_YEARS = 2          # how much OHLCV history to keep per ticker
EVENT_LOOKBACK_DAYS = 400  # how far back to detect events

# Tuned on real data (2026-07-23): loose thresholds flagged ~35% of trading
# days. These keep only genuinely notable moves — roughly 10-25 per stock/yr.
EVENT_ZSCORE = 2.4         # |return| in std-devs of trailing 60d returns
EVENT_ABS_PCT = 6.0        # or absolute % move (whichever triggers first)
EVENT_VOLUME_RATIO = 3.5   # volume vs 20d average (with a >=2% move)
EVENT_GAP_PCT = 4.0        # open vs previous close
EVENT_MAX_PER_TICKER = 40  # keep the most recent N (bounds UI + file size)

EVENT_SEVERITY_BANDS = [(6.0, 1), (9.0, 2), (13.0, 3)]  # (|pct| >= x, severity)

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
# LLM — Google Gemini (free tier). Set GEMINI_API_KEY to enable; without it the
# pipeline falls back to rule-based summaries and skips translation.
# Free-tier limits are per-minute/per-day, so the LLM budget below is GLOBAL
# per run (not per ticker) and calls are batched + throttled.
# --------------------------------------------------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_TOKENS = 2048
GEMINI_DELAY_SEC = 7.0         # spacing between calls → stay under free-tier RPM (~10/min)

LLM_ENABLED = True             # falls back to rules automatically without a key
LLM_MAX_EVENTS_PER_RUN = 60    # GLOBAL cap on AI event summaries per run
LLM_RECENT_DAYS = 60           # only AI-summarize events newer than this
LLM_EVENT_BATCH = 6            # events per Gemini call

# Translation is OFF by default — the free Gemini quota is reserved for AI event
# analysis (confidence + cause). Flip TRANSLATE_FOREIGN back on to auto-translate
# foreign news (it will then compete with summaries for quota).
TRANSLATE_FOREIGN = False      # auto-translate US/GLOBAL news to Korean
TRANSLATE_FEED_TOP = 20        # translate only the top-N feed items when enabled
TRANSLATE_TICKER_NEWS = False  # translate ticker news via new calls? (cache reuse always on)
TRANSLATE_BATCH = 15           # strings per translation call
TRANSLATE_MAX_ITEMS = 200      # hard cap on translated strings per run


def gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


def telegram_token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN") or None


def telegram_chat_id() -> str | None:
    """첫 번째 수신자. 여러 명을 받으려면 `telegram_chat_ids()`를 쓴다."""
    ids = telegram_chat_ids()
    return ids[0] if ids else None


def telegram_chat_ids() -> list[str]:
    """수신자 목록.

    `TELEGRAM_CHAT_ID`에 콤마·공백·줄바꿈으로 여러 개를 넣을 수 있다.
    값이 하나뿐이면 길이 1 리스트라 기존 단일 수신자 동작과 완전히 같다.

        TELEGRAM_CHAT_ID=123456789
        TELEGRAM_CHAT_ID=123456789,987654321,-1001234567890

    개인 chat_id는 상대가 봇에게 먼저 `/start`를 보낸 뒤에야 잡힌다
    (텔레그램은 봇이 먼저 DM을 걸지 못한다). `telegram-whoami`로 확인할 것.
    음수 ID는 그룹/채널이다.
    """
    raw = os.getenv("TELEGRAM_CHAT_ID") or ""
    out: list[str] = []
    for part in re.split(r"[,\s]+", raw):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def universe(market: str) -> list[tuple[str, str, str, list[str]]]:
    return KR_UNIVERSE if market.upper() == "KR" else US_UNIVERSE


def all_universe() -> list[dict]:
    """Flattened universe with market tags, used by most modules.

    ETFs carry ``isEtf: True`` so the per-ticker pipeline can skip the expensive
    single-company news fetch + event backfill for them.
    """
    out: list[dict] = []
    groups = (
        ("KR", KR_UNIVERSE, False), ("US", US_UNIVERSE, False),
        ("KR", KR_ETF, True), ("US", US_ETF, True),
    )
    for market, rows, is_etf in groups:
        for code, name, exchange, aliases in rows:
            out.append({
                "code": code,
                "name": name,
                "market": market,
                "exchange": exchange,
                "aliases": aliases,
                "currency": "KRW" if market == "KR" else "USD",
                "isEtf": is_etf,
            })
    return out
