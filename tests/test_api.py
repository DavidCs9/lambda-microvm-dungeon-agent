from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dungeon_agent.api.config import Settings
from dungeon_agent.api.main import create_app
from tests.test_adventure import proposal, sample_plan, sample_player


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(workspace_dir=tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_adventure_and_turn_persist_in_world(client: TestClient) -> None:
    started = client.put(
        "/v1/adventure",
        json={
            "language": "en",
            "plan": sample_plan().model_dump(mode="json"),
            "player_character": sample_player().model_dump(mode="json"),
        },
    )
    assert started.status_code == 200
    assert started.json()["plan"]["title"] == "The Storm Bell"

    response = client.post(
        "/v1/turns",
        json={
            "action": "I improvise a bridge",
            "proposal": proposal(requires_roll=False, difficulty=None).model_dump(mode="json"),
        },
    )
    assert response.status_code == 200
    world = response.json()
    assert world["revision"] == 1
    assert world["last_result"]["action"] == "I improvise a bridge"
    assert client.get("/v1/world").json() == world


def test_language_can_be_selected_while_planning(client: TestClient) -> None:
    response = client.put("/v1/language", json={"language": "es"})

    assert response.status_code == 200
    assert response.json()["language"] == "es"
    assert response.json()["status"] == "planning"


@pytest.mark.parametrize("path", ["/v1/adventure", "/v1/turns"])
def test_invalid_payload_is_rejected(client: TestClient, path: str) -> None:
    assert client.put(path, json={}).status_code in {405, 422}
    assert client.post(path, json={}).status_code in {405, 422}


def test_unknown_route_returns_not_found(client: TestClient) -> None:
    assert client.get("/missing").status_code == 404


def test_invalid_dm_state_change_returns_explainable_conflict(client: TestClient) -> None:
    client.put(
        "/v1/adventure",
        json={
            "language": "en",
            "plan": sample_plan().model_dump(mode="json"),
            "player_character": sample_player().model_dump(mode="json"),
        },
    )
    invalid = proposal(
        requires_roll=False,
        difficulty=None,
        success_changes={"add_items": ["imaginary_sword"]},
    )

    response = client.post(
        "/v1/turns",
        json={"action": "summon a sword", "proposal": invalid.model_dump(mode="json")},
    )

    assert response.status_code == 409
    assert "unknown item" in response.json()["detail"]
