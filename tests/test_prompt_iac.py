import json
from pathlib import Path

from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, TurnProposal

TEMPLATE = Path(__file__).parents[1] / "infra" / "control-plane" / "workflow" / "template.yaml"


def _without_null_defaults(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_null_defaults(item)
            for key, item in value.items()
            if not (key == "default" and item is None)
        }
    if isinstance(value, list):
        return [_without_null_defaults(item) for item in value]
    return value


def test_managed_prompts_and_versions_are_owned_by_cloudformation() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "AllowMethods: [DELETE, GET, POST]" in template
    assert template.count("Type: Custom::BedrockManagedPrompt\n") == 3
    assert "Type: AWS::Lambda::Function\n" in template
    assert "bedrock:CreatePromptVersion" in template
    assert "CampaignPromptArn:" not in template
    assert "CharacterPromptArn:" not in template
    assert "MasterPromptArn:" not in template
    assert "225989371926:prompt/" not in template
    assert "BEDROCK_RUNTIME_CONFIG_PARAMETER: !Ref RuntimeConfigParameterName" in template
    assert "ssm:GetParameter" in template
    assert "CAMPAIGN_PROMPT_ARN: !GetAtt CampaignManagedPrompt.Arn" not in template
    assert "CHARACTER_PROMPT_ARN: !GetAtt CharacterManagedPrompt.Arn" not in template
    assert "MASTER_PROMPT_ARN: !GetAtt MasterManagedPrompt.Arn" not in template
    assert "ModelId: !Ref CampaignModelId" in template
    assert "ModelId: !Ref CharacterModelId" in template
    assert "ModelId: !Ref MasterModelId" in template
    assert "bedrock:RenderPrompt" in template
    assert "converted[api_key] = schema_value(item)" in template
    assert "converted[api_key] = int(item)" in template
    assert "converted[api_key] = float(item)" in template


def test_managed_prompt_tool_schemas_match_domain_contracts() -> None:
    embedded = [
        json.loads(line.split("Json:", maxsplit=1)[1].strip())
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("Json: {")
    ]

    assert embedded == [
        _without_null_defaults(AdventurePlan.model_json_schema()),
        _without_null_defaults(PlayerCharacter.model_json_schema()),
        _without_null_defaults(TurnProposal.model_json_schema()),
    ]
