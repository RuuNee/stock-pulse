# 테스트 픽스처

## `indicators_parity.json`

차트 지표 수식이 두 곳에 있다 — `pipeline/analyze/technical.py::series()` 와
`web/src/lib/indicators.ts`. 종목 JSON 에서 `indicators` 를 빼면서(2026-08-20,
파일의 절반을 차지해 `.git` 증식의 주범이었다) 실데이터로 대조할 수 없게 됐다.
그래서 이 픽스처를 양쪽에서 각각 검사한다.

- 파이썬: `tests/test_indicators_parity.py`
- 웹: `npm run check-indicators` (web CI 에서 돈다)

`volMa20` 은 차트가 쓰지 않아 계약에서 뺐다.

### 재생성

수식을 의도적으로 바꿨을 때만. 바꾼 값이 맞는지 먼저 확인하고 돌릴 것 —
이 파일이 기준선이라 무심코 재생성하면 검사가 아무것도 안 잡는다.

```bash
python - <<'PY'
import json, sys; sys.path.insert(0, '.')
import pandas as pd
from pipeline.analyze import technical

rows = json.load(open('data/tickers/US/AAPL.json', encoding='utf-8'))['ohlcv']['rows'][-200:]
df = pd.DataFrame(rows, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
df['Date'] = pd.to_datetime(df['Date']); df = df.set_index('Date')
ser = technical.series(df); ser.pop('volMa20', None)

old = json.load(open('tests/fixtures/indicators_parity.json', encoding='utf-8'))
json.dump({**old, 'rows': rows, 'expected': ser},
          open('tests/fixtures/indicators_parity.json', 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
PY
```
