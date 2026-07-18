import json
import time
from typing import TypeVar

from mypy_boto3_bedrock_runtime import BedrockRuntimeClient
from pydantic import BaseModel, ValidationError

from dungeon_agent.api.models import AdventurePlan, LanguageCode, TurnProposal
from dungeon_agent.orchestrator.observability import SessionMetrics

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredBedrockAgent:
    """Invoke a model through a required, schema-validated Converse tool."""

    def __init__(
        self,
        client: BedrockRuntimeClient,
        model_id: str,
        metrics: SessionMetrics,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.metrics = metrics

    def invoke(
        self,
        *,
        system: str,
        prompt: str,
        tool_name: str,
        tool_description: str,
        output_model: type[OutputModel],
        max_tokens: int,
        temperature: float,
    ) -> OutputModel:
        current_prompt = prompt
        current_temperature = temperature
        for attempt in range(2):
            try:
                return self._invoke_once(
                    system=system,
                    prompt=current_prompt,
                    tool_name=tool_name,
                    tool_description=tool_description,
                    output_model=output_model,
                    max_tokens=max_tokens,
                    temperature=current_temperature,
                )
            except ValidationError as error:
                if attempt == 1:
                    raise
                current_prompt = (
                    f"{prompt}\n\nYour previous tool output failed validation. Correct every "
                    f"error below and call {tool_name} again with a complete object:\n"
                    f"{str(error)[:1_500]}"
                )
                current_temperature = min(temperature, 0.3)
        raise RuntimeError("structured output repair exhausted")

    def _invoke_once(
        self,
        *,
        system: str,
        prompt: str,
        tool_name: str,
        tool_description: str,
        output_model: type[OutputModel],
        max_tokens: int,
        temperature: float,
    ) -> OutputModel:
        started = time.perf_counter()
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool_name,
                            "description": tool_description,
                            "inputSchema": {"json": output_model.model_json_schema()},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": tool_name}},
            },
            requestMetadata={
                "project": "lambda-microvm-dungeon-agent",
                "agent_role": tool_name,
            },
        )
        usage = response["usage"]
        self.metrics.record(
            input_tokens=usage["inputTokens"],
            output_tokens=usage["outputTokens"],
            latency_ms=(time.perf_counter() - started) * 1_000,
        )
        content = response["output"]["message"]["content"]
        for block in content:
            tool_use = block.get("toolUse")
            if tool_use is not None and tool_use["name"] == tool_name:
                return output_model.model_validate(tool_use["input"])
        raise RuntimeError(f"Bedrock did not call required tool {tool_name}")


class AdventureArchitect:
    """Create one small, replayable adventure for a new session."""

    def __init__(self, agent: StructuredBedrockAgent) -> None:
        self.agent = agent

    def create(self, language: LanguageCode) -> AdventurePlan:
        language_name = "Spanish" if language == "es" else "English"
        return self.agent.invoke(
            system=(
                "You design compact tabletop fantasy one-shots. Create coherent, playful "
                "adventures that support improvisation and at least three meaningfully different "
                "solutions. Keep the lore simple enough to understand immediately. IDs must be "
                "lowercase ASCII snake_case. Every exit must reference a declared location. Do not "
                "copy commercial settings, characters, or stories."
            ),
            prompt=(
                f"Create a brand-new 10 to 15 minute adventure entirely in {language_name}. "
                "Give it one clear objective, 3 to 5 connected locations, 1 or 2 characters with "
                "useful motivations, a few usable items, and secrets that permit clever solutions. "
                "The opening must state the immediate situation and objective without solving it. "
                "Populate every field in the tool, including secrets and max_turns. Keep every "
                "description and motivation under 250 characters."
            ),
            tool_name="create_adventure",
            tool_description="Return the complete validated adventure plan.",
            output_model=AdventurePlan,
            max_tokens=3_000,
            temperature=0.9,
        )


class DungeonMaster:
    """Interpret a free-form player action into two validated outcome branches."""

    def __init__(self, agent: StructuredBedrockAgent, language: LanguageCode) -> None:
        self.agent = agent
        self.language = language

    def adjudicate(
        self,
        action: str,
        world: dict[str, object],
        rejection_feedback: str | None = None,
    ) -> TurnProposal:
        language_name = "Spanish" if self.language == "es" else "English"
        return self.agent.invoke(
            system=(
                "You are a fair, energetic tabletop dungeon master. Reward creative ideas and "
                "allow plausible approaches that were not anticipated by the adventure author. "
                "Use a d20 roll only when an action is risky or uncertain; obvious actions succeed "
                "automatically. A difficulty of 8 is easy, 12 moderate, 15 hard, and 18 extreme. "
                "Never claim state changes only in narration: encode every location, item, fact, "
                "health, or victory change in the matching changes object. Only use declared IDs. "
                "Summarize intent in fewer than 200 characters. "
                "Set objective_complete only when the stated objective is genuinely accomplished. "
                "Failures should move the story forward with a consequence, not simply reject the "
                "idea. Keep each narration to 1 to 3 vivid sentences and never act for the player."
            ),
            prompt=json.dumps(
                {
                    "instruction": f"Resolve this turn entirely in {language_name}.",
                    "playerAction": action,
                    "world": world,
                    "previousProposalRejection": rejection_feedback,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            tool_name="resolve_turn",
            tool_description="Return the success and failure branches for this player action.",
            output_model=TurnProposal,
            max_tokens=1_200,
            temperature=0.65,
        )
