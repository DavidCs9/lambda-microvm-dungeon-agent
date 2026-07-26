"""Runtime-selectable Bedrock model and managed-prompt configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from dungeon_agent.plane_shared.agents.bedrock import StructuredBedrockAgent


class ParameterClient(Protocol):
    def get_parameter(self, *, Name: str, WithDecryption: bool = False) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgentRuntimeConfig:
    model_id: str
    prompt_arn: str | None = None

    @property
    def target(self) -> str:
        return self.prompt_arn or self.model_id


class RuntimeConfigProvider:
    """Load the active role configuration from SSM on every model invocation."""

    def __init__(
        self,
        client: ParameterClient | None,
        parameter_name: str | None,
        legacy: dict[str, AgentRuntimeConfig],
    ) -> None:
        self._client = client
        self._parameter_name = parameter_name
        self._legacy = legacy

    def get(self, role: str) -> AgentRuntimeConfig:
        if self._client is None or self._parameter_name is None:
            return self._legacy_config(role)
        response = self._client.get_parameter(Name=self._parameter_name, WithDecryption=False)
        try:
            document = json.loads(response["Parameter"]["Value"])
            role_config = document["roles"][role]
            model_id = role_config["model_id"]
            prompt_arn = role_config.get("prompt_arn")
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid Bedrock runtime config for role {role}") from error
        if not isinstance(model_id, str) or not model_id:
            raise ValueError(f"runtime config has no model_id for role {role}")
        if prompt_arn is not None and not isinstance(prompt_arn, str):
            raise ValueError(f"runtime config has invalid prompt_arn for role {role}")
        return AgentRuntimeConfig(model_id=model_id, prompt_arn=prompt_arn)

    def _legacy_config(self, role: str) -> AgentRuntimeConfig:
        try:
            return self._legacy[role]
        except KeyError as error:
            raise ValueError(f"no Bedrock runtime config for role {role}") from error


class RuntimeConfiguredBedrockAgent:
    """Resolve the active target immediately before each Bedrock call."""

    def __init__(self, client: Any, config: RuntimeConfigProvider, role: str) -> None:
        self._client = client
        self._config = config
        self._role = role

    def invoke(self, **kwargs: Any) -> Any:
        config = self._config.get(self._role)
        request_metadata = dict(kwargs.pop("request_metadata", {}) or {})
        metrics = kwargs.pop("metrics", None)
        if metrics is not None:
            metrics.model_id = config.model_id
        request_metadata.update(
            {
                "runtime_role": self._role,
                "runtime_model_id": config.model_id,
                "runtime_prompt_arn": config.prompt_arn or "none",
            }
        )
        return StructuredBedrockAgent(self._client, config.target, metrics=metrics).invoke(
            request_metadata=request_metadata,
            **kwargs,
        )
