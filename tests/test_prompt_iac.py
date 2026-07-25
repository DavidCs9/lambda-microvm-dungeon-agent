import json
from pathlib import Path

from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, TurnProposal

TEMPLATE = Path(__file__).parents[1] / "infra" / "control-plane" / "workflow" / "template.yaml"


def test_managed_prompts_and_versions_are_owned_by_cloudformation() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert template.count("Type: AWS::Bedrock::Prompt\n") == 3
    assert template.count("Type: AWS::Bedrock::PromptVersion\n") == 3
    assert "CampaignPromptArn:" not in template
    assert "CharacterPromptArn:" not in template
    assert "MasterPromptArn:" not in template
    assert "225989371926:prompt/" not in template
    assert "CAMPAIGN_PROMPT_ARN: !Ref CampaignPromptVersion" in template
    assert "CHARACTER_PROMPT_ARN: !Ref CharacterPromptVersion" in template
    assert "MASTER_PROMPT_ARN: !Ref MasterPromptVersion" in template
    assert "ModelId: !Ref CampaignModelId" in template
    assert "ModelId: !Ref CharacterModelId" in template
    assert "ModelId: !Ref MasterModelId" in template


def test_managed_prompt_tool_schemas_match_domain_contracts() -> None:
    embedded = [
        json.loads(line.split("Json:", maxsplit=1)[1].strip())
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("Json: {")
    ]

    assert embedded == [
        AdventurePlan.model_json_schema(),
        PlayerCharacter.model_json_schema(),
        TurnProposal.model_json_schema(),
    ]
