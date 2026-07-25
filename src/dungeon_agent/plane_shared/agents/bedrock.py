from __future__ import annotations

import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class StructuredBedrockAgent:
    """Invoke a model through one required, schema-validated Converse tool."""

    def __init__(
        self,
        client: Any,
        model_id: str,
        metrics: Any | None = None,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.metrics = metrics

    def invoke(
        self,
        *,
        system: str,
        prompt: str,
        prompt_variables: dict[str, str] | None = None,
        tool_name: str,
        tool_description: str,
        output_model: type[OutputModel],
        max_tokens: int,
        temperature: float,
    ) -> OutputModel:
        current_prompt = prompt
        current_variables = (
            None
            if prompt_variables is None
            else {
                **prompt_variables,
                "repair_feedback": "No previous validation failure.",
            }
        )
        current_temperature = temperature
        for attempt in range(3):
            try:
                return self._invoke_once(
                    system=system,
                    prompt=current_prompt,
                    prompt_variables=current_variables,
                    tool_name=tool_name,
                    tool_description=tool_description,
                    output_model=output_model,
                    max_tokens=max_tokens,
                    temperature=current_temperature,
                )
            except ValidationError as error:
                if attempt == 2:
                    raise
                current_prompt = (
                    f"{prompt}\n\nYour previous tool output failed validation. Correct every "
                    f"error below and call {tool_name} again with a complete object:\n"
                    f"{str(error)[:1_500]}"
                )
                if current_variables is not None:
                    current_variables["repair_feedback"] = (
                        "Your previous tool output failed validation. Correct every error below "
                        f"and call {tool_name} again with a complete object:\n{str(error)[:1_500]}"
                    )
                current_temperature = min(temperature, 0.3)
        raise RuntimeError("structured output repair exhausted")

    def _invoke_once(
        self,
        *,
        system: str,
        prompt: str,
        prompt_variables: dict[str, str] | None,
        tool_name: str,
        tool_description: str,
        output_model: type[OutputModel],
        max_tokens: int,
        temperature: float,
    ) -> OutputModel:
        started = time.perf_counter()
        request: dict[str, Any] = {
            "modelId": self.model_id,
            "requestMetadata": {
                "project": "lambda-microvm-dungeon-agent",
                "agent_role": tool_name,
            },
        }
        if ":prompt/" in self.model_id:
            if prompt_variables is None:
                raise ValueError("managed prompts require prompt_variables")
            request["promptVariables"] = {
                name: {"text": value} for name, value in prompt_variables.items()
            }
        else:
            request.update(
                {
                    "system": [{"text": system}],
                    "messages": [{"role": "user", "content": [{"text": prompt}]}],
                    "inferenceConfig": {
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                    "toolConfig": {
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
                }
            )
        response = self.client.converse(**request)
        if self.metrics is not None:
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
