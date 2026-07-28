"""`pipeline` 을 저장소 루트에서 import 할 수 있게 한다 (pytest 실행 위치 무관)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
