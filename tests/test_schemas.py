"""응답 계약 — result_to_dict의 실제 출력이 OpenAPI에 선언한 InspectResponse와 어긋나지 않는다."""
import pytest

from app.eval.adversarial_tasks import ADVERSARIAL
from app.eval.tasks import GOLDEN
from app.schemas import InspectResponse
from app.service import get_supervisor, result_to_dict


@pytest.mark.parametrize("task", GOLDEN + ADVERSARIAL, ids=lambda t: t.id)
def test_response_matches_declared_contract(task):
    d = result_to_dict(get_supervisor().handle(task.question, image_path=task.image_path))
    InspectResponse.model_validate(d)


def test_openapi_declares_inspect_response():
    pytest.importorskip("fastapi")  # CI 경량 환경엔 fastapi가 없다
    from app.server import app

    spec = app.openapi()
    schema = spec["paths"]["/inspect"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/InspectResponse"}
