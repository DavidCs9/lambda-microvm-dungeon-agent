from types import TracebackType
from typing import Self, cast

from mypy_boto3_lambda_microvms import LambdaMicroVMsClient

from dungeon_agent.api.models import AdventurePlan, LanguageCode, TurnProposal
from dungeon_agent.microvm import request_json, require_success, wait_for_state


class MicrovmSession:
    """Own one MicroVM lifecycle and its authenticated backend connection."""

    def __init__(self, client: LambdaMicroVMsClient, image_arn: str, image_version: str) -> None:
        self.client = client
        self.image_arn = image_arn
        self.image_version = image_version
        self.microvm_id: str | None = None
        self.endpoint: str | None = None
        self.token: str | None = None

    def __enter__(self) -> Self:
        region = self.client.meta.region_name
        ingress_connector = (
            f"arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:ALL_INGRESS"
        )
        internet_egress_connector = (
            f"arn:aws:lambda:{region}:aws:network-connector:aws-network-connector:INTERNET_EGRESS"
        )
        response = self.client.run_microvm(
            imageIdentifier=self.image_arn,
            imageVersion=self.image_version,
            ingressNetworkConnectors=[ingress_connector],
            egressNetworkConnectors=[internet_egress_connector],
            idlePolicy={
                "maxIdleDurationSeconds": 300,
                "suspendedDurationSeconds": 300,
                "autoResumeEnabled": True,
            },
            maximumDurationInSeconds=1_800,
            logging={"disabled": {}},
        )
        self.microvm_id = response["microvmId"]
        self.endpoint = response["endpoint"]
        wait_for_state(self.client, self.microvm_id, "RUNNING")
        token_response = self.client.create_microvm_auth_token(
            microvmIdentifier=self.microvm_id,
            expirationInMinutes=30,
            allowedPorts=[{"port": 8080}],
        )
        self.token = token_response["authToken"]["X-aws-proxy-auth"]
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        if self.microvm_id is not None:
            self.client.terminate_microvm(microvmIdentifier=self.microvm_id)
            wait_for_state(self.client, self.microvm_id, "TERMINATED")

    def read_world(self) -> dict[str, object]:
        result = request_json(self._endpoint(), self._token(), "GET", "/v1/world")
        require_success(result, "read world")
        return self._world_from(result.body)

    def set_language(self, language: LanguageCode) -> dict[str, object]:
        result = request_json(
            self._endpoint(), self._token(), "PUT", "/v1/language", {"language": language}
        )
        require_success(result, "set language")
        return self._world_from(result.body)

    def start_adventure(self, language: LanguageCode, plan: AdventurePlan) -> dict[str, object]:
        result = request_json(
            self._endpoint(),
            self._token(),
            "PUT",
            "/v1/adventure",
            {"language": language, "plan": plan.model_dump(mode="json")},
        )
        require_success(result, "start adventure")
        return self._world_from(result.body)

    def apply_turn(self, action: str, proposal: TurnProposal) -> dict[str, object]:
        result = request_json(
            self._endpoint(),
            self._token(),
            "POST",
            "/v1/turns",
            {"action": action, "proposal": proposal.model_dump(mode="json")},
        )
        require_success(result, "apply turn")
        return self._world_from(result.body)

    @staticmethod
    def _world_from(body: object) -> dict[str, object]:
        if not isinstance(body, dict):
            raise RuntimeError("MicroVM returned a non-object world state")
        return cast(dict[str, object], body)

    def _endpoint(self) -> str:
        if self.endpoint is None:
            raise RuntimeError("MicroVM session has not started")
        return self.endpoint

    def _token(self) -> str:
        if self.token is None:
            raise RuntimeError("MicroVM session has not started")
        return self.token
