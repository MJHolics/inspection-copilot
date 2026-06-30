"""라인 실시간 모니터링 — 센서 스트림에서 이상을 탐지해 검사 코파일럿에 신호를 넘긴다.

PRODUCT.md 아키텍처의 'MQTT 라인 모니터링' 기둥. transport는 **플러그블**하다:
  - `SimulatedSource` — 인프로세스 결정적 스트림(브로커 불요·무료·테스트 가능). 기본/데모용.
  - `MqttSource` — 실 MQTT 브로커 구독(paho-mqtt). **MQTT-ready 인터페이스**: 키/브로커가
    있으면 그대로 끼운다. (브로커가 필요해 무료 데모에선 미실행 — Vertex-ready와 같은 표기.)

탐지기는 순수 stdlib(롤링 z-score)라 네트워크 없이 단위테스트된다. 새 supervisor 에이전트를
추가하지 않으므로 라우팅/eval에 회귀가 없다 — 모니터는 이상 이벤트를 만들고, 코파일럿은
그 이벤트(예: "L3 진동 이상")를 받아 기존 에이전트로 SOP를 그라운딩한다(핸드오프).
"""
from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass


@dataclass
class SensorReading:
    line: str          # 예: "L1"
    metric: str        # 예: "vibration"
    value: float
    ts: int            # 단조 증가 틱


@dataclass
class AnomalyEvent:
    line: str
    metric: str
    value: float
    zscore: float
    ts: int


class RollingAnomalyDetector:
    """(line, metric)별 롤링 윈도우 z-score 이상탐지(온라인·순수).

    현재 값을 *과거* 윈도우 통계에 비추어 z-score를 보고, **`persist`틱 연속**으로 임계를
    넘을 때만 이상으로 본다. 단발 센서 노이즈(가우시안 꼬리)는 무시하고 *지속되는* 라인
    이상만 잡아 오탐을 줄인다(라인 모니터링의 현실적 설계). 표본이 적으면 판정 보류.
    """

    def __init__(self, window: int = 20, z: float = 3.0, min_samples: int = 8,
                 persist: int = 2) -> None:
        self.window = window
        self.z = z
        self.min_samples = min_samples
        self.persist = persist
        self._buf: dict[tuple[str, str], deque] = {}
        self._streak: dict[tuple[str, str], int] = {}

    def update(self, r: SensorReading) -> AnomalyEvent | None:
        key = (r.line, r.metric)
        buf = self._buf.setdefault(key, deque(maxlen=self.window))
        event = None
        if len(buf) >= self.min_samples:
            mu = statistics.fmean(buf)
            sd = statistics.pstdev(buf) or 1e-9
            zscore = abs(r.value - mu) / sd
            if zscore > self.z:
                self._streak[key] = self._streak.get(key, 0) + 1
                if self._streak[key] >= self.persist:
                    event = AnomalyEvent(r.line, r.metric, r.value, round(zscore, 2), r.ts)
            else:
                self._streak[key] = 0
        buf.append(r.value)
        return event


class SimulatedSource:
    """결정적 합성 센서 스트림(브로커 불요). 한 라인에 이상 스파이크를 주입한다."""

    def __init__(self, lines=("L1", "L2", "L3"), ticks: int = 60,
                 anomaly_line: str = "L3", seed: int = 7) -> None:
        self.lines = lines
        self.ticks = ticks
        self.anomaly_line = anomaly_line
        self.seed = seed

    def stream(self):
        import random

        rng = random.Random(self.seed)
        for t in range(self.ticks):
            for line in self.lines:
                base = rng.gauss(1.0, 0.05)  # 정상 진동(평균 1.0)
                # 이상 라인은 중반 구간에 큰 스파이크
                if line == self.anomaly_line and 30 <= t < 35:
                    base += rng.uniform(0.6, 1.0)
                yield SensorReading(line=line, metric="vibration", value=round(base, 4), ts=t)


class MqttSource:
    """실 MQTT 브로커 구독(MQTT-ready). 브로커가 있으면 끼운다 — 무료 데모에선 미실행.

    구현 시 paho-mqtt로 topic 구독 → 메시지 페이로드를 SensorReading으로 파싱해 yield.
    """

    def __init__(self, host: str, topic: str, port: int = 1883) -> None:
        self.host, self.topic, self.port = host, topic, port

    def stream(self):  # pragma: no cover - 브로커 필요(무료 데모 범위 밖)
        raise NotImplementedError(
            "MqttSource는 실 MQTT 브로커가 필요합니다(무료 데모 범위 밖). "
            "paho-mqtt로 토픽을 구독해 페이로드를 SensorReading으로 파싱하세요. "
            "데모는 SimulatedSource를 쓰며, 동일 인터페이스(.stream())라 그대로 교체됩니다."
        )


def run_monitor(source, detector: RollingAnomalyDetector) -> list[AnomalyEvent]:
    """소스 스트림을 흘려 이상 이벤트 목록을 반환한다(소스/탐지기 모두 주입 가능)."""
    return [ev for r in source.stream() if (ev := detector.update(r)) is not None]
