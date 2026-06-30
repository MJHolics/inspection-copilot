"""InspectOps 라인 모니터링 데모 — 스트림 이상탐지 → 코파일럿 핸드오프.

라인 센서 스트림(시뮬레이션, 브로커 불요)을 흘려 이상을 탐지하고, 가장 빈번히 이상이 난
라인에 대해 검사 코파일럿(기존 Supervisor)에 "처리 SOP"를 물어 그라운딩한다. 즉 모니터가
신호를 만들고 코파일럿이 근거를 댄다 — 새 라우팅 에이전트 없이(eval 회귀 0) 통합을 보인다.

  python monitor_demo.py
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from collections import Counter  # noqa: E402

from app import db  # noqa: E402
from app.eval.run_eval import _build_supervisor, _stub_sql, _stub_vision  # noqa: E402
from app.monitoring import RollingAnomalyDetector, SimulatedSource, run_monitor  # noqa: E402


def main() -> None:
    print("=" * 72)
    print("InspectOps 라인 모니터링 — 시뮬레이션 스트림(브로커 불요·결정적)")
    print("=" * 72)

    # 1) 라인 스트림 이상탐지(transport는 플러그블 — MqttSource로 교체 가능).
    events = run_monitor(SimulatedSource(anomaly_line="L3", seed=7),
                         RollingAnomalyDetector(window=20, z=3.0, min_samples=8))
    by_line = Counter(e.line for e in events)
    print(f"\n● 탐지된 이상 이벤트 {len(events)}건 · 라인별 {dict(by_line)}")
    for e in events[:5]:
        print(f"   - t={e.ts} {e.line}/{e.metric} value={e.value} z={e.zscore}")

    if not events:
        print("이상 없음 — 정상 운전."); return

    # 2) 코파일럿 핸드오프: 가장 이상이 잦은 라인의 결함 처리 SOP를 그라운딩.
    worst = by_line.most_common(1)[0][0]
    print(f"\n● 코파일럿 핸드오프 — '{worst}' 라인 이상 다발 → 처리 절차 질의")
    db.build_db()
    sup = _build_supervisor(sql_llm=_stub_sql, vision_predictor=_stub_vision)
    res = sup.handle("스크래치 결함은 어떤 절차로 처리해?")  # 모니터 신호 → 코파일럿 SOP
    print(f"   라우팅: {' → '.join(res.plan.steps)} · 검증: {'🛑 사람검토' if res.needs_human else '✅'}")
    for r in res.results:
        print(f"   - {r.agent}(신뢰도 {r.confidence:.2f}): {r.summary[:70]}")

    print("\n" + "=" * 72)
    print("4대 벽: 라인 모니터링이 ②신규/이상 신호를 만들고, 코파일럿이 ④비전문가용으로 근거를 댄다.")
    print("        실 MQTT는 app.monitoring.MqttSource(동일 인터페이스)로 교체 — MQTT-ready.")


if __name__ == "__main__":
    main()
