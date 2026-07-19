from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dungeon_agent.control_plane.agents import (
    AdventureArchitect,
    CharacterArchitect,
    StructuredBedrockAgent,
)
from dungeon_agent.orchestrator.observability import SessionMetrics
from tests.test_adventure import sample_plan, sample_player


def response_for(tool_name: str, tool_input: dict[str, object]) -> dict[str, object]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tool-1",
                            "name": tool_name,
                            "input": tool_input,
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 120, "outputTokens": 80, "totalTokens": 200},
        "metrics": {"latencyMs": 50},
    }


def test_structured_agent_validates_tool_output_and_tracks_usage() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_adventure", sample_plan().model_dump(mode="json")
    )
    metrics = SessionMetrics.start("test-model")
    agent = StructuredBedrockAgent(client, "test-model", metrics)

    result = agent.invoke(
        system="Design a game",
        prompt="Make a new adventure",
        tool_name="create_adventure",
        tool_description="Create it",
        output_model=type(sample_plan()),
        max_tokens=2_000,
        temperature=0.9,
    )

    assert result.title == "The Storm Bell"
    assert metrics.total_tokens == 200
    request = client.converse.call_args.kwargs
    assert request["inferenceConfig"]["maxTokens"] == 2_000
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": "create_adventure"}}


def test_structured_agent_rejects_invalid_model_output() -> None:
    client = Mock()
    client.converse.return_value = response_for("create_adventure", {"title": "Incomplete"})
    agent = StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))

    with pytest.raises(ValidationError):
        agent.invoke(
            system="Design a game",
            prompt="Make a new adventure",
            tool_name="create_adventure",
            tool_description="Create it",
            output_model=type(sample_plan()),
            max_tokens=2_000,
            temperature=0.9,
        )
    assert client.converse.call_count == 2


def test_structured_agent_repairs_invalid_output_once() -> None:
    client = Mock()
    client.converse.side_effect = [
        response_for("create_adventure", {"title": "Incomplete"}),
        response_for("create_adventure", sample_plan().model_dump(mode="json")),
    ]
    agent = StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))

    result = agent.invoke(
        system="Design a game",
        prompt="Make a new adventure",
        tool_name="create_adventure",
        tool_description="Create it",
        output_model=type(sample_plan()),
        max_tokens=2_000,
        temperature=0.9,
    )

    assert result.title == "The Storm Bell"
    repaired_request = client.converse.call_args_list[1].kwargs
    assert (
        "previous tool output failed validation"
        in repaired_request["messages"][0]["content"][0]["text"]
    )
    assert repaired_request["inferenceConfig"]["temperature"] == 0.3


def test_character_architect_grounds_protagonist_in_adventure() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_player_character", sample_player().model_dump(mode="json")
    )
    architect = CharacterArchitect(
        StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))
    )

    character = architect.create("es", sample_plan())

    assert character.name == "Iria Vale"
    request = client.converse.call_args.kwargs
    prompt = request["messages"][0]["content"][0]["text"]
    assert '"adventure"' in prompt
    assert "Spanish" in prompt


def test_adventure_architect_injects_theme_seed_into_prompt() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_adventure", sample_plan().model_dump(mode="json")
    )
    architect = AdventureArchitect(
        StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))
    )

    architect.create("es", theme_seed="a ferry stuck between two dawns")

    request = client.converse.call_args.kwargs
    prompt = request["messages"][0]["content"][0]["text"]
    system = request["system"][0]["text"]
    assert "a ferry stuck between two dawns" in prompt
    assert "Spanish" in prompt
    assert "silenced village bell" in system
