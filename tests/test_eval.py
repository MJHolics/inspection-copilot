"""Eval 하네스 테스트 — 지표 순수함수 + 골든셋 러너 스모크. 오프라인·결정적."""
from __future__ import annotations

from app.eval.metrics import CaseResult, aggregate, route_exact, route_jaccard
from app.eval.run_eval import run
from app.eval.tasks import GOLDEN


def test_route_exact():
    assert route_exact(["a", "b"], ["a", "b"])
    assert not route_exact(["b", "a"], ["a", "b"])  # 순서 중요


def test_route_jaccard():
    assert route_jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert route_jaccard(["a"], ["a", "b"]) == 0.5
    assert route_jaccard([], []) == 1.0


def test_aggregate_mixed():
    cases = [
        CaseResult("1", ["knowledge"], ["knowledge"], True, 1.0, True, True, True, 5),
        CaseResult("2", ["analytics"], ["knowledge"], False, 0.0, True, None, False, 15),
    ]
    s = aggregate(cases)
    assert s["count"] == 2
    assert s["routing_exact_acc"] == 0.5
    assert s["gate_acc"] == 1.0
    assert s["grounding_acc"] == 1.0  # 적용 대상(1건)만 집계
    assert s["e2e_success_rate"] == 0.5


def test_runner_on_golden_set():
    cases, summary = run()
    assert summary["count"] == len(GOLDEN)
    # 현재 시스템은 골든셋에서 완벽 — 회귀 시 이 수치가 떨어져 잡힌다.
    assert summary["routing_exact_acc"] == 1.0
    assert summary["grounding_acc"] == 1.0
    assert summary["gate_acc"] == 1.0
    assert summary["e2e_success_rate"] == 1.0


def test_grounding_cases_have_sources():
    grounded = [t for t in GOLDEN if "grounding" in t.tags]
    assert grounded and all(t.expected_top_source for t in grounded)


def test_adversarial_suite_runs_and_stresses():
    """적대적 셋은 (1) 라우터 보정 덕에 routing 1.0이지만 (2) TF-IDF 그라운딩 한계로
    e2e < 1.0이어야 한다 — '실패를 실제로 잡는' 셋임을 회귀로 고정(키·dense 불요)."""
    from app.eval.adversarial_tasks import ADVERSARIAL
    cases, summary = run(ADVERSARIAL)  # 기본 TF-IDF
    assert summary["count"] == len(ADVERSARIAL)
    assert summary["routing_exact_acc"] == 1.0          # 충돌 보정 효과 고정
    assert summary["e2e_success_rate"] < 1.0            # 동의어·다국어·가드레일 갭이 남아야 의미 있음


def test_adversarial_tasks_have_rationale():
    from app.eval.adversarial_tasks import ADVERSARIAL
    assert ADVERSARIAL and all(t.note for t in ADVERSARIAL)  # 채점 근거 명시(자의성 방지)
