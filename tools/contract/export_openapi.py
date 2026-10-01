"""OpenAPI 스키마를 web/openapi.json으로 내보낸다 — 프론트 타입 생성(openapi-typescript)의 입력.

  python tools/contract/export_openapi.py            # → web/openapi.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.server import app

    out = ROOT / "web" / "openapi.json"
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
