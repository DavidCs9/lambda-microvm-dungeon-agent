from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dungeon_agent.api.config import Settings
from dungeon_agent.api.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(workspace_dir=tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_ready(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_action_persists_in_world_state(client: TestClient) -> None:
    action = "Take the brass key"

    response = client.post("/v1/actions", json={"action": action})

    assert response.status_code == 200
    world = response.json()
    assert world["revision"] == 1
    assert world["story"][-1] == action
    assert client.get("/v1/world").json() == world


@pytest.mark.parametrize(
    "payload",
    [
        {"action": ""},
        {"action": "   "},
        {"action": "x" * 501},
        {"action": "valid", "unexpected": True},
    ],
)
def test_invalid_actions_are_rejected(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post("/v1/actions", json=payload)

    assert response.status_code == 422


def test_unknown_route_returns_not_found(client: TestClient) -> None:
    assert client.get("/missing").status_code == 404
