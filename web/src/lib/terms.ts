// Beginner glossary (UIUX §3-1). Keys are used by <Term k="per">. Each entry:
// short one-liner + a plain-language "그래서 뭘 보면 되나".

export interface TermEntry {
  title: string;
  short: string;
  more?: string;
}

export const TERMS: Record<string, TermEntry> = {
  per: {
    title: "PER (주가수익비율)",
    short: "주가가 회사가 버는 1년 이익의 몇 배인지. 10배면 지금 이익이 10년 쌓여야 주가만큼 됩니다.",
    more: "낮을수록 싸다고 보지만, 성장 기대가 없어 낮은 경우도 많아요.",
  },
  pbr: {
    title: "PBR (주가순자산비율)",
    short: "회사가 가진 순자산 대비 주가가 몇 배인지. 1배면 청산가치와 주가가 같은 셈입니다.",
  },
  roe: {
    title: "ROE (자기자본이익률)",
    short: "회사가 자기 돈으로 얼마나 효율적으로 이익을 내는지. 높을수록 장사를 잘하는 회사예요.",
  },
  eps: { title: "EPS (주당순이익)", short: "주식 1주가 벌어들인 이익. 이게 커질수록 주가도 오를 힘이 생깁니다." },
  marcap: { title: "시가총액", short: "회사 전체의 시장 가격. 주가 × 총 주식 수. 회사의 몸집을 나타냅니다." },
  volume: { title: "거래량", short: "그날 사고팔린 주식 수. 많으면 그만큼 관심이 뜨겁다는 뜻이에요." },
  amount: { title: "거래대금", short: "그날 거래된 돈의 총액. 거래량 × 가격. 시장의 열기를 봅니다." },
  ma: {
    title: "이동평균선",
    short: "최근 며칠 종가의 평균을 이은 선. 20일선이면 최근 20일 평균 흐름을 보여줍니다.",
    more: "주가가 이동평균선 위에 있으면 최근 분위기가 좋다는 신호로 봅니다.",
  },
  goldencross: { title: "골든크로스", short: "짧은 이동평균선이 긴 선을 아래에서 위로 뚫는 것. 상승 신호로 해석돼요." },
  deadcross: { title: "데드크로스", short: "짧은 이동평균선이 긴 선을 위에서 아래로 뚫는 것. 하락 신호로 봅니다." },
  rsi: {
    title: "RSI",
    short: "0~100 사이 값으로 과열/침체를 봅니다. 70 이상이면 너무 올랐고, 30 이하면 너무 내렸다고 해석해요.",
  },
  vix: { title: "VIX (공포지수)", short: "투자자들의 불안 정도. 20을 넘으면 시장이 겁먹었다는 뜻입니다." },
  foreign: { title: "외국인 수급", short: "외국인 투자자가 사는지 파는지. 국내 증시에 영향이 큽니다." },
  institution: { title: "기관 수급", short: "연기금·자산운용사 등 큰손이 사는지 파는지를 봅니다." },
  short: { title: "공매도", short: "주식을 빌려 먼저 팔고 나중에 싸게 사서 갚는 거래. 하락에 베팅하는 방법이에요." },
  dividend: { title: "배당수익률", short: "주가 대비 1년에 받는 배당금 비율. 은행 이자처럼 생각하면 쉬워요." },
  kospi: { title: "코스피", short: "한국 대표 기업들을 모은 시장. 이 지수가 오르면 큰 기업들이 대체로 올랐다는 뜻이에요." },
  kosdaq: { title: "코스닥", short: "중소·벤처기업 중심 시장. 코스피보다 출렁임이 큽니다." },
  sp500: { title: "S&P 500", short: "미국 대표 기업 500곳의 평균. 세계 증시의 기준으로 쓰여요." },
  nasdaq: { title: "나스닥", short: "기술주가 많이 모인 미국 시장. 금리에 민감하게 반응합니다." },
  dow: { title: "다우존스", short: "미국 전통 대형 기업 30곳을 묶은 지수예요." },
  fx: { title: "환율", short: "1달러를 사는 데 드는 원화. 오르면 외국인이 한국 주식을 팔 유인이 커집니다." },
  rate: { title: "기준금리", short: "중앙은행이 정하는 기준 이자율. 오르면 대출이 부담돼 주식에 불리할 수 있어요." },
  ytnx: { title: "국채금리", short: "정부가 돈 빌릴 때 내는 이자. 오르면 주식보다 채권이 매력적이 됩니다." },
  inflation: { title: "인플레이션", short: "물가가 오르는 것. 심하면 금리 인상으로 이어져 주식에 부담이 됩니다." },
  fomc: { title: "FOMC", short: "미국의 금리를 결정하는 회의. 결과에 따라 전 세계 증시가 출렁여요." },
  earning: { title: "어닝서프라이즈", short: "실적이 예상보다 훨씬 좋게 나온 것. 주가가 크게 오르는 계기가 됩니다." },
  guidance: { title: "가이던스", short: "회사가 스스로 밝히는 앞으로의 실적 전망. 실제 실적만큼 중요하게 봅니다." },
  gap: { title: "갭 상승/하락", short: "전날 종가보다 훌쩍 뛰거나 떨어진 채로 장이 시작하는 것을 말해요." },
  circuit: { title: "서킷브레이커", short: "주가가 너무 급하게 떨어지면 잠시 거래를 멈추는 안전장치입니다." },
  etf: { title: "ETF", short: "여러 종목을 한 바구니에 담아 거래하는 상품. 하나만 사도 분산 투자가 됩니다." },
  zscore: { title: "표준편차(σ)", short: "평소 움직임과 비교해 얼마나 튀는 날인지. 2σ면 최근 몇 달 중 손에 꼽는 변동이에요." },
};

export function hasTerm(key: string): boolean {
  return key in TERMS;
}
