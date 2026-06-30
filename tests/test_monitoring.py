"""라인 모니터링 — 롤링 z-score 이상탐지 단위테스트(순수·결정적, 브로커 불요)."""
from __future__ import annotations

from app.monitoring import (
    RollingAnomalyDetector,
    SensorReading,
    SimulatedSource,
    run_monitor,
)


def test_normal_stream_no_anomaly():
    """정상 변동만 있으면 알람이 없어야 한다(오탐 방지)."""
    det = RollingAnomalyDetector(window=20, z=3.0, min_samples=8)
    import random

    rng = random.Random(0)
    events = []
    for t in range(80):
        ev = det.update(SensorReading("L1", "vibration", rng.gauss(1.0, 0.05), t))
        if ev:
            events.append(ev)
    assert events == [], f"정상 스트림 오탐: {events}"


def test_sustained_spike_is_detected():
    """안정 구간 뒤 *지속* 스파이크(persist틱 연속)는 잡혀야 한다."""
    det = RollingAnomalyDetector(window=20, z=3.0, min_samples=8, persist=2)
    for t in range(20):
        det.update(SensorReading("L2", "vibration", 1.0, t))  # 안정
    first = det.update(SensorReading("L2", "vibration", 5.0, 20))   # 1틱째: 보류
    second = det.update(SensorReading("L2", "vibration", 5.0, 21))  # 2틱째: 발동
    assert first is None
    assert second is not None and second.line == "L2" and second.zscore > 3.0


def test_single_spike_held_by_persistence():
    """단발 스파이크는 지속성 요구로 무시한다(노이즈 오탐 방지)."""
    det = RollingAnomalyDetector(window=20, z=3.0, min_samples=8, persist=2)
    for t in range(20):
        det.update(SensorReading("L1", "vibration", 1.0, t))
    assert det.update(SensorReading("L1", "vibration", 5.0, 20)) is None  # 1틱뿐


def test_min_samples_holds_judgment():
    """표본이 부족하면 판정을 보류(초기 변동에 오탐하지 않음)."""
    det = RollingAnomalyDetector(window=20, z=3.0, min_samples=8)
    assert det.update(SensorReading("L1", "vibration", 99.0, 0)) is None


def test_simulated_source_flags_injected_line():
    """시뮬레이션 소스의 주입 이상이 해당 라인에서 잡히는지(결정적)."""
    events = run_monitor(SimulatedSource(anomaly_line="L3", seed=7),
                         RollingAnomalyDetector(window=20, z=3.0, min_samples=8))
    assert events, "주입 이상이 하나도 안 잡힘"
    assert all(e.line == "L3" for e in events), f"이상 라인 오검: {[e.line for e in events]}"
