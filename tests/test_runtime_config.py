from unittest.mock import Mock

import pytest

from dungeon_agent.control_plane.runtime_config import AgentRuntimeConfig, RuntimeConfigProvider


def test_runtime_config_reads_all_role_fields_from_parameter() -> None:
    client = Mock()
    client.get_parameter.return_value = {
        "Parameter": {
            "Value": (
                '{"schema_version":1,"roles":{"campaign":{"model_id":"haiku",'
                '"prompt_arn":"arn:campaign"},"character":{"model_id":"haiku",'
                '"prompt_arn":"arn:character"},"master":{"model_id":"haiku",'
                '"prompt_arn":"arn:master"}}}'
            )
        }
    }
    provider = RuntimeConfigProvider(client, "dungeon-agent/runtime", {})

    assert provider.get("campaign").target == "arn:campaign"
    assert provider.get("character").model_id == "haiku"
    client.get_parameter.assert_called_with(Name="dungeon-agent/runtime", WithDecryption=False)
    assert client.get_parameter.call_count == 2


def test_runtime_config_falls_back_to_legacy_values() -> None:
    provider = RuntimeConfigProvider(
        None,
        None,
        {"campaign": AgentRuntimeConfig(model_id="legacy-model")},
    )

    assert provider.get("campaign").target == "legacy-model"
    with pytest.raises(ValueError, match="no Bedrock runtime config"):
        provider.get("master")


def test_runtime_config_rejects_missing_role() -> None:
    client = Mock()
    client.get_parameter.return_value = {"Parameter": {"Value": '{"roles":{}}'}}
    provider = RuntimeConfigProvider(client, "dungeon-agent/runtime", {})

    with pytest.raises(ValueError, match="invalid Bedrock runtime config"):
        provider.get("campaign")
