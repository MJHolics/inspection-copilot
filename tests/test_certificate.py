"""검사 성적서 테스트 — 판정 규칙·SOP 발췌·NMS. 모델 없이 스텁 주입으로 오프라인."""
import numpy as np

from app.certificate import issue, load_sop
from app.detector import Box, _nms

# config.DEFECT_CLASSES 순서: crazing, inclusion, patches, pitted_surface, rolled-in_scale, scratches
CONFIDENT_SCRATCH = [0.01, 0.01, 0.01, 0.01, 0.01, 0.95]
UNSURE = [0.05, 0.05, 0.30, 0.05, 0.05, 0.50]


def _pred(probs):
    return lambda _path: probs


def _det(*boxes):
    return lambda _path: list(boxes)


def test_two_models_agree_is_automatic():
    cert = issue("x.jpg", _pred(CONFIDENT_SCRATCH), _det(Box("scratches", 0.8, (0.1, 0.1, 0.3, 0.9))))
    assert not cert.needs_human
    assert cert.verdict.startswith("결함 확인")
    assert len(cert.boxes) == 1


def test_detector_disagrees_stops():
    cert = issue("x.jpg", _pred(CONFIDENT_SCRATCH), _det(Box("inclusion", 0.8, (0.1, 0.1, 0.3, 0.9))))
    assert cert.needs_human
    assert cert.verdict == "사람 확인 필요"
    assert cert.actions[0].startswith("자동 판정을 보류")


def test_detector_finds_nothing_stops():
    assert issue("x.jpg", _pred(CONFIDENT_SCRATCH), _det()).needs_human


def test_low_confidence_stops_even_if_detector_agrees():
    cert = issue("x.jpg", _pred(UNSURE), _det(Box("scratches", 0.9, (0.1, 0.1, 0.3, 0.9))))
    assert cert.needs_human


def test_without_detector_classifier_alone_decides():
    cert = issue("x.jpg", _pred(CONFIDENT_SCRATCH), None)
    assert not cert.needs_human
    assert cert.boxes == []


def test_sop_is_quoted_from_document():
    sop_id, criteria, actions = load_sop("scratches")
    assert sop_id == "SOP-SCR"
    assert any("5mm" in c for c in criteria)
    assert len(actions) == 3


def test_missing_sop_falls_back_to_general():
    sop_id, criteria, actions = load_sop("patches")
    assert sop_id == "SOP-GEN"
    assert criteria == []
    assert actions


def test_nms_drops_overlapping_lower_score():
    boxes = np.array([[0.0, 0.0, 0.5, 0.5], [0.02, 0.02, 0.5, 0.5], [0.6, 0.6, 0.9, 0.9]])
    scores = np.array([0.9, 0.8, 0.7])
    assert _nms(boxes, scores, 0.5) == [0, 2]
