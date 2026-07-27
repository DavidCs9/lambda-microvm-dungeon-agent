from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from dungeon_agent.control_plane.agents.roles import (
    _CREATIVE_PROFILE_FAMILIES,
    AdventureArchitect,
    CharacterArchitect,
    _has_language_leak,
    campaign_theme_family,
    campaign_theme_seed,
)
from dungeon_agent.data_plane.agents.roles import DungeonMaster
from dungeon_agent.orchestrator.observability import SessionMetrics
from dungeon_agent.plane_shared.agents.bedrock import StructuredBedrockAgent
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
    assert client.converse.call_count == 3


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


def test_structured_agent_invokes_versioned_managed_prompt() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_adventure", sample_plan().model_dump(mode="json")
    )
    prompt_arn = "arn:aws:bedrock:us-east-2:123456789012:prompt/ABCDEFGHIJ:3"
    agent = StructuredBedrockAgent(client, prompt_arn)

    result = agent.invoke(
        system="Ignored because it is managed",
        prompt="Ignored because it is managed",
        prompt_variables={"language_name": "Spanish", "theme": "a glass harbor"},
        tool_name="create_adventure",
        tool_description="Managed by the prompt",
        output_model=type(sample_plan()),
        max_tokens=2_000,
        temperature=0.9,
    )

    assert result.title == "The Storm Bell"
    request = client.converse.call_args.kwargs
    assert request["modelId"] == prompt_arn
    assert request["promptVariables"] == {
        "language_name": {"text": "Spanish"},
        "theme": {"text": "a glass harbor"},
        "repair_feedback": {"text": "No previous validation failure."},
    }
    assert "system" not in request
    assert "messages" not in request
    assert "inferenceConfig" not in request
    assert "toolConfig" not in request


def test_structured_agent_repairs_managed_prompt_with_feedback_variable() -> None:
    client = Mock()
    client.converse.side_effect = [
        response_for("create_adventure", {"title": "Incomplete"}),
        response_for("create_adventure", sample_plan().model_dump(mode="json")),
    ]
    agent = StructuredBedrockAgent(
        client,
        "arn:aws:bedrock:us-east-2:123456789012:prompt/ABCDEFGHIJ:3",
    )

    agent.invoke(
        system="ignored",
        prompt="ignored",
        prompt_variables={"language_name": "English", "theme": "a glass harbor"},
        tool_name="create_adventure",
        tool_description="managed",
        output_model=type(sample_plan()),
        max_tokens=2_000,
        temperature=0.9,
    )

    repaired = client.converse.call_args_list[1].kwargs
    assert "failed validation" in repaired["promptVariables"]["repair_feedback"]["text"]


def test_character_architect_grounds_protagonist_in_adventure() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_player_character", sample_player().model_dump(mode="json")
    )
    architect = CharacterArchitect(
        StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))
    )

    character = architect.create("es", sample_plan(), pronoun_seed="él / lo")

    assert character.name == "Iria Vale"
    request = client.converse.call_args.kwargs
    prompt = request["messages"][0]["content"][0]["text"]
    system = request["system"][0]["text"]
    assert '"adventure"' in prompt
    assert "Spanish" in prompt
    assert "él / lo" in prompt
    assert "vary gender/presentation" in system


def test_adventure_architect_injects_theme_seed_into_prompt() -> None:
    client = Mock()
    client.converse.return_value = response_for(
        "create_adventure", sample_plan().model_dump(mode="json")
    )
    architect = AdventureArchitect(
        StructuredBedrockAgent(client, "test-model", SessionMetrics.start("test-model"))
    )

    architect.create("en", theme_seed="a ferry stuck between two dawns")

    request = client.converse.call_args.kwargs
    prompt = request["messages"][0]["content"][0]["text"]
    system = request["system"][0]["text"]
    assert "a ferry stuck between two dawns" in prompt
    assert "English" in prompt
    assert "silent bell/tower" in system


def test_campaign_theme_seed_is_stable_but_varies_by_campaign() -> None:
    first = campaign_theme_seed("cam_01J00000000000000000000001")
    same = campaign_theme_seed("cam_01J00000000000000000000001")
    other = campaign_theme_seed("cam_01J00000000000000000000002")

    assert first == same
    assert first != other
    assert "floating market" not in first


def test_campaign_theme_families_are_balanced() -> None:
    assert len(_CREATIVE_PROFILE_FAMILIES) == 4
    assert {name for name, _profiles in _CREATIVE_PROFILE_FAMILIES} == {
        "action",
        "exploration",
        "social",
        "mystery",
    }
    assert all(len(profiles) == 4 for _name, profiles in _CREATIVE_PROFILE_FAMILIES)


def test_campaign_theme_family_is_stable_and_covers_all_families() -> None:
    campaign_ids = [f"cam_01J0000000000000000000{i:02d}" for i in range(64)]
    families = {campaign_theme_family(identifier) for identifier in campaign_ids}

    assert len(families) == 4
    assert campaign_theme_family(campaign_ids[0]) == campaign_theme_family(campaign_ids[0])


def test_adventure_language_guard_catches_hybrid_output() -> None:
    assert _has_language_leak(sample_plan(), "es")
    assert not _has_language_leak(sample_plan(), "en")


def test_dungeon_master_rejects_unknown_item_without_model_call() -> None:
    agent = Mock()
    master = DungeonMaster(agent, "en")
    world: dict[str, object] = {
        "plan": sample_plan().model_dump(mode="json"),
        "inventory": ["chalk"],
    }

    proposal = master.adjudicate("I throw an archive key into the ravine.", world)

    assert not proposal.requires_roll
    assert proposal.stat is None
    assert proposal.difficulty is None
    assert proposal.failure_changes.add_facts == ["The unknown item cannot change the world."]
    agent.invoke.assert_not_called()


def test_dungeon_master_uses_model_for_known_item_action() -> None:
    agent = Mock()
    agent.invoke.return_value = sample_player()
    master = DungeonMaster(agent, "en")
    world: dict[str, object] = {
        "plan": sample_plan().model_dump(mode="json"),
        "inventory": ["chalk"],
    }

    master.adjudicate("I use the Wayfinder Chalk.", world)

    agent.invoke.assert_called_once()
