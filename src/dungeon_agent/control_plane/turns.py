"""Authoritative player turns: Dungeon Master proposal, MicroVM ruling, durable events."""

import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal, cast

from dungeon_agent.control_plane.agents.roles import DungeonMaster, StructuredAgentPort
from dungeon_agent.control_plane.domain.enums import EventType, SessionPhase, SessionStatus
from dungeon_agent.control_plane.domain.models import (
    DiceRolledPayload,
    PhaseChangedPayload,
    SessionCompletedPayload,
    SessionRecord,
    SubmitTurnCommand,
    TurnCompletedPayload,
)
from dungeon_agent.control_plane.events import append_session_event, utc_now
from dungeon_agent.control_plane.microvms.manager import TurnRejectedError
from dungeon_agent.control_plane.telemetry.emf import EmfTelemetry

Clock = Callable[[], datetime]


class TurnWorker:
    """Apply one checked-out player action and report the authoritative outcome."""

    def __init__(
        self,
        store: Any,
        snapshots: Any,
        agent: StructuredAgentPort,
        microvms: Any,
        *,
        delivery: Any | None = None,
        telemetry: EmfTelemetry | None = None,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._snapshots = snapshots
        self._agent = agent
        self._microvms = microvms
        self._delivery = delivery
        self._telemetry = telemetry
        self._clock = clock or utc_now
        self._monotonic = monotonic

    def handle(self, raw_command: Mapping[str, object]) -> dict[str, object]:
        command = SubmitTurnCommand.model_validate(raw_command)
        started = self._monotonic()
        try:
            outcome = self._run(command)
        except Exception as error:
            self._fail(command, error)
            return {"turnId": command.turn_id, "status": "failed"}
        latency_ms = (self._monotonic() - started) * 1_000
        if self._telemetry is not None and outcome != "skipped":
            self._telemetry.phase(
                "turn",
                outcome,
                latency_ms,
                session_id=command.session_id,
                correlation_id=command.correlation_id,
            )
        return {"turnId": command.turn_id, "status": outcome}

    def _run(self, command: SubmitTurnCommand) -> str:
        session = self._store.get(command.session_id)
        if (
            session is None
            or session.owner_id != command.owner_id
            or session.status is not SessionStatus.ACTIVE
            or session.last_turn_id != command.turn_id
        ):
            # The worker is invoked asynchronously; a duplicate delivery must not replay.
            return "skipped"

        snapshot = self._snapshots.load(command.session_id)
        microvm_id = session.active_microvm_id
        if microvm_id is None:
            raise RuntimeError("active session has no MicroVM")
        if not self._microvms.is_running(microvm_id):
            replacement = self._microvms.rehydrate(command.session_id, snapshot)
            try:
                self._microvms.terminate(microvm_id)
            except Exception as cleanup_error:
                print(f"old MicroVM cleanup failed: {type(cleanup_error).__name__}")
            session = self._save(
                session.model_copy(
                    update={
                        "active_microvm_id": replacement.microvm_id,
                        "revision": session.revision + 1,
                        "updated_at": self._clock(),
                    }
                )
            )
            microvm_id = replacement.microvm_id

        world_prompt = cast(dict[str, object], snapshot.model_dump(mode="json"))
        dungeon_master = DungeonMaster(self._agent, session.language)
        proposal = dungeon_master.adjudicate(command.action, world_prompt)
        try:
            world = self._microvms.apply_turn(microvm_id, command.action, proposal)
        except TurnRejectedError as error:
            proposal = dungeon_master.adjudicate(command.action, world_prompt, str(error)[:500])
            world = self._microvms.apply_turn(microvm_id, command.action, proposal)

        self._snapshots.save(command.session_id, world)
        result = world.last_result
        if result is None:
            raise RuntimeError("MicroVM returned no turn result")

        finished = world.status in {"won", "lost"}
        session = self._save(
            session.model_copy(
                update={
                    "status": SessionStatus.COMPLETED if finished else SessionStatus.READY,
                    "phase": SessionPhase.COMPLETED if finished else SessionPhase.READY,
                    "revision": session.revision + 1,
                    "updated_at": self._clock(),
                }
            )
        )
        now = self._clock()
        if result.roll is not None:
            assert result.difficulty is not None
            self._emit(
                command,
                EventType.DICE_ROLLED,
                DiceRolledPayload(
                    turn_id=command.turn_id,
                    roll=result.roll,
                    difficulty=result.difficulty,
                    success=result.success,
                ),
                now,
            )
        self._emit(
            command,
            EventType.TURN_COMPLETED,
            TurnCompletedPayload(
                turn_id=command.turn_id,
                revision=session.revision,
                narration=result.narration,
                action=command.action,
            ),
            now,
        )
        if finished:
            self._emit(
                command,
                EventType.SESSION_COMPLETED,
                SessionCompletedPayload(
                    outcome=cast(Literal["won", "lost"], world.status),
                    revision=session.revision,
                ),
                now,
            )
        return "completed"

    def _fail(self, command: SubmitTurnCommand, error: Exception) -> None:
        print(f"turn {command.turn_id} failed: {type(error).__name__}: {error}")
        try:
            session = self._store.get(command.session_id)
            if session is None or session.status is not SessionStatus.ACTIVE:
                return
            session = self._save(
                session.model_copy(
                    update={
                        "status": SessionStatus.READY,
                        "phase": SessionPhase.READY,
                        "revision": session.revision + 1,
                        "updated_at": self._clock(),
                    }
                )
            )
            self._emit(
                command,
                EventType.SESSION_PHASE_CHANGED,
                PhaseChangedPayload(
                    phase=SessionPhase.READY,
                    elapsed_ms=0,
                    revision=session.revision,
                ),
                self._clock(),
            )
        except Exception as rollback_error:
            print(f"turn rollback failed: {type(rollback_error).__name__}")

    def _save(self, session: SessionRecord) -> SessionRecord:
        validated = SessionRecord.model_validate(session)
        saved = self._store.save(validated, expected_revision=validated.revision - 1)
        return SessionRecord.model_validate(saved)

    def _emit(
        self,
        command: SubmitTurnCommand,
        event_type: EventType,
        payload: DiceRolledPayload
        | TurnCompletedPayload
        | SessionCompletedPayload
        | PhaseChangedPayload,
        now: datetime,
    ) -> None:
        append_session_event(
            self._store,
            self._delivery,
            command.session_id,
            event_type,
            payload,
            command.correlation_id,
            now,
        )
