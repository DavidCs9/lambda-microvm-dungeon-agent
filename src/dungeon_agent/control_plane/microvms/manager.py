"""Pragmatic adapter around the Lambda MicroVM lifecycle API."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from dungeon_agent.control_plane.domain.models import MicrovmLaunchResult, SessionId
from dungeon_agent.domain.game import AdventurePlan, LanguageCode, PlayerCharacter, WorldState
from dungeon_agent.microvm import HttpResult, request_json

_TERMINAL_STATES = {"TERMINATED"}


class LambdaMicrovmsClient(Protocol):
    """Small subset of the generated Lambda MicroVM client used by this adapter."""

    def list_microvm_images(self, *, nameFilter: str, maxResults: int) -> Mapping[str, object]: ...

    def get_microvm_image(self, *, imageIdentifier: str) -> Mapping[str, object]: ...

    def run_microvm(
        self,
        *,
        imageIdentifier: str,
        imageVersion: str,
        ingressNetworkConnectors: Sequence[str],
        egressNetworkConnectors: Sequence[str],
        idlePolicy: Mapping[str, object],
        maximumDurationInSeconds: int,
        logging: Mapping[str, object],
        clientToken: str,
    ) -> Mapping[str, object]: ...

    def get_microvm(self, *, microvmIdentifier: str) -> Mapping[str, object]: ...

    def create_microvm_auth_token(
        self,
        *,
        microvmIdentifier: str,
        expirationInMinutes: int,
        allowedPorts: Sequence[Mapping[str, int]],
    ) -> Mapping[str, object]: ...

    def terminate_microvm(self, *, microvmIdentifier: str) -> Mapping[str, object]: ...


class JsonRequester(Protocol):
    def __call__(
        self,
        endpoint: str,
        token: str,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> HttpResult: ...


class MicrovmMetrics(Protocol):
    """Optional timing hook used by a Lambda handler or tests."""

    def record(self, operation: str, latency_ms: float) -> None: ...


class _NullMetrics:
    def record(self, operation: str, latency_ms: float) -> None:
        del operation, latency_ms


class RehydrationNotSupportedError(RuntimeError):
    """Raised when the current MicroVM API cannot restore a supplied snapshot."""


@dataclass(frozen=True)
class _ImageVersion:
    arn: str
    version: str


class LambdaMicrovmManager:
    """Resolve the latest image and own one MicroVM's complete lifecycle."""

    def __init__(
        self,
        client: LambdaMicrovmsClient,
        image_name_or_arn: str,
        region: str,
        *,
        requester: JsonRequester = request_json,
        metrics: MicrovmMetrics | None = None,
        timeout_seconds: float = 180,
        poll_interval_seconds: float = 1,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._image_name_or_arn = image_name_or_arn
        self._region = region
        self._requester = requester
        self._metrics = metrics or _NullMetrics()
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._sleep = sleep

    def launch(self, session_id: SessionId) -> MicrovmLaunchResult:
        image = self._timed("image_resolution", self._resolve_latest_image)
        started = self._monotonic()
        response = self._client.run_microvm(
            imageIdentifier=image.arn,
            imageVersion=image.version,
            ingressNetworkConnectors=[self._connector("ALL_INGRESS")],
            egressNetworkConnectors=[self._connector("INTERNET_EGRESS")],
            idlePolicy={
                "maxIdleDurationSeconds": 300,
                "suspendedDurationSeconds": 300,
                "autoResumeEnabled": True,
            },
            maximumDurationInSeconds=1_800,
            logging={"disabled": {}},
            clientToken=str(session_id),
        )
        self._metrics.record("launch", self._elapsed_ms(started))
        microvm_id = self._required_string(response, "microvmId")
        try:
            self._timed("readiness", lambda: self.wait_until_running(microvm_id))
        except Exception as error:
            try:
                self.terminate(microvm_id)
            except Exception as cleanup_error:
                error.add_note(f"MicroVM cleanup also failed: {cleanup_error}")
            raise
        return MicrovmLaunchResult(microvm_id=microvm_id, ready_at=self._now())

    def wait_until_running(self, microvm_id: str) -> Mapping[str, object]:
        return self._wait_for_state(microvm_id, "RUNNING")

    def initialize(
        self,
        microvm_id: str,
        language: LanguageCode,
        adventure: AdventurePlan,
        character: PlayerCharacter,
    ) -> WorldState:
        started = self._monotonic()
        microvm = self._client.get_microvm(microvmIdentifier=microvm_id)
        if microvm.get("state") != "RUNNING":
            microvm = self.wait_until_running(microvm_id)
        endpoint = self._required_string(microvm, "endpoint")
        token_response = self._client.create_microvm_auth_token(
            microvmIdentifier=microvm_id,
            expirationInMinutes=30,
            allowedPorts=[{"port": 8080}],
        )
        auth_token = token_response.get("authToken")
        if not isinstance(auth_token, Mapping):
            raise RuntimeError("MicroVM auth response did not contain authToken")
        token = self._required_string(cast(Mapping[str, object], auth_token), "X-aws-proxy-auth")
        result = self._requester(
            endpoint,
            token,
            "PUT",
            "/v1/adventure",
            {
                "language": language,
                "plan": cast(dict[str, object], adventure.model_dump(mode="json")),
                "player_character": cast(dict[str, object], character.model_dump(mode="json")),
            },
        )
        if not 200 <= result.status < 300:
            raise RuntimeError(f"initialize MicroVM returned HTTP {result.status}: {result.body}")
        world = WorldState.model_validate(result.body)
        self._metrics.record("initialization", self._elapsed_ms(started))
        return world

    def rehydrate(self, session_id: SessionId, state: WorldState) -> MicrovmLaunchResult:
        self._require_rehydratable_state(state)
        assert state.plan is not None
        assert state.player_character is not None
        started = self._monotonic()
        launch = self.launch(session_id)
        try:
            restored = self.initialize(
                launch.microvm_id,
                state.language,
                state.plan,
                state.player_character,
            )
            if restored != state:
                raise RehydrationNotSupportedError(
                    "MicroVM initialization did not reproduce the requested snapshot"
                )
        except Exception as error:
            try:
                self.terminate(launch.microvm_id)
            except Exception as cleanup_error:
                error.add_note(f"MicroVM cleanup also failed: {cleanup_error}")
            raise
        self._metrics.record("rehydration", self._elapsed_ms(started))
        return launch

    def terminate(self, microvm_id: str) -> None:
        started = self._monotonic()
        self._client.terminate_microvm(microvmIdentifier=microvm_id)
        self._wait_for_state(microvm_id, "TERMINATED")
        self._metrics.record("termination", self._elapsed_ms(started))

    def _resolve_latest_image(self) -> _ImageVersion:
        image_identifier = self._image_name_or_arn
        if not image_identifier.startswith("arn:"):
            response = self._client.list_microvm_images(
                nameFilter=image_identifier,
                maxResults=50,
            )
            items = response.get("items")
            if not isinstance(items, list):
                raise RuntimeError("MicroVM image listing did not contain items")
            matches = [
                item
                for item in items
                if isinstance(item, Mapping) and item.get("name") == image_identifier
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one MicroVM image named {image_identifier!r}, found {len(matches)}"
                )
            image_identifier = self._required_string(matches[0], "imageArn")

        image = self._client.get_microvm_image(imageIdentifier=image_identifier)
        return _ImageVersion(
            arn=self._required_string(image, "imageArn"),
            version=self._required_string(image, "latestActiveImageVersion"),
        )

    def _wait_for_state(self, microvm_id: str, expected_state: str) -> Mapping[str, object]:
        deadline = self._monotonic() + self._timeout_seconds
        while self._monotonic() < deadline:
            response = self._client.get_microvm(microvmIdentifier=microvm_id)
            state = response.get("state")
            if state == expected_state:
                return response
            if state in _TERMINAL_STATES and state != expected_state:
                reason = response.get("stateReason", "No state reason returned")
                raise RuntimeError(f"MicroVM entered {state}: {reason}")
            self._sleep(self._poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for MicroVM {microvm_id} to reach {expected_state}")

    def _require_rehydratable_state(self, state: WorldState) -> None:
        if state.plan is None or state.player_character is None:
            raise RehydrationNotSupportedError("Cannot rehydrate a world without an adventure")
        is_initial = (
            state.revision == 0
            and state.status == "active"
            and state.location_id == state.plan.starting_location_id
            and not state.inventory
            and state.health == 3
            and not state.facts
            and state.last_result is None
        )
        if not is_initial:
            raise RehydrationNotSupportedError(
                "The current MicroVM API can only restore an initial adventure; "
                "it has no full-state restore endpoint"
            )

    def _connector(self, connector: str) -> str:
        return (
            f"arn:aws:lambda:{self._region}:aws:network-connector:aws-network-connector:{connector}"
        )

    def _timed[T](self, operation: str, function: Callable[[], T]) -> T:
        started = self._monotonic()
        result = function()
        self._metrics.record(operation, self._elapsed_ms(started))
        return result

    def _elapsed_ms(self, started: float) -> float:
        return (self._monotonic() - started) * 1_000

    @staticmethod
    def _required_string(values: Mapping[str, object], key: str) -> str:
        value = values.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"MicroVM response did not contain {key}")
        return value
