"""DynamoDB single-table adapter for sessions, idempotency, and ordered events."""

from collections.abc import Mapping

from dungeon_agent.control_plane.domain.enums import SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.persistence.dynamo_helpers import (
    AttributeValue,
    DynamoDbAggregateStore,
    attribute_int,
    attribute_string,
    create_dynamodb_client,
    event_item,
    metadata_item,
    string,
)
from dungeon_agent.control_plane.persistence.dynamo_types import DynamoDbClient
from dungeon_agent.control_plane.persistence.errors import (
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)

_ACTIVE_STATUS_VALUES = tuple(
    status.value
    for status in (
        SessionStatus.REQUESTED,
        SessionStatus.CREATING,
        SessionStatus.READY,
        SessionStatus.ACTIVE,
    )
)


class DynamoDbControlPlaneRepository:
    """Implement session and event ports with a DynamoDB single-table layout.

    Access patterns:

    - ``PK=SESSION#{id}, SK=METADATA`` stores the session.
    - ``PK=OWNER#{owner}, SK=IDEMPOTENCY#{key}`` maps duplicate creates.
    - ``PK=SESSION#{id}, SK=EVENT#{sequence}`` stores ordered events.
    """

    def __init__(
        self,
        client: DynamoDbClient,
        table_name: str,
        *,
        idempotency_ttl_seconds: int = 86_400,
    ) -> None:
        if not table_name:
            raise ValueError("table_name must not be empty")
        if idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._table = DynamoDbAggregateStore(client, table_name, "SESSION")
        self._idempotency_ttl_seconds = idempotency_ttl_seconds

    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord:
        """Atomically persist a session and its owner-scoped idempotency record."""
        existing = self.find_by_idempotency_key(session.owner_id, idempotency_key)
        if existing is not None:
            return existing

        try:
            self._table.create_with_idempotency(
                aggregate_item=self._session_item(session),
                owner_id=session.owner_id,
                idempotency_key=idempotency_key,
                aggregate_id_attr="sessionId",
                aggregate_id=session.session_id,
                created_at=session.created_at,
                ttl_seconds=self._idempotency_ttl_seconds,
            )
        except self._table.transaction_cancelled as error:
            # A concurrent duplicate is successful idempotency. A collision on only the
            # session key is a real conflict and must remain visible to the caller.
            existing = self.find_by_idempotency_key(session.owner_id, idempotency_key)
            if existing is not None:
                return existing
            raise SessionAlreadyExistsError(
                f"session or idempotency record already exists: {session.session_id}"
            ) from error
        return session

    def get(self, session_id: SessionId) -> SessionRecord | None:
        """Read a session consistently so revision checks see recent writes."""
        raw_item = self._table.get_metadata_item(session_id)
        if raw_item is None:
            return None
        return self._session_from_item(raw_item)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> SessionRecord | None:
        """Resolve an owner-scoped idempotency key to its original session."""
        session_id = self._table.get_idempotency_id(owner_id, idempotency_key, "sessionId")
        if session_id is None:
            return None
        return self.get(session_id)

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord:
        """Save one state revision without overwriting the independent event counter."""
        if session.revision != expected_revision + 1:
            raise SessionRevisionConflictError(
                "saved session revision must be exactly one greater than expected revision"
            )
        try:
            attributes = self._table.save_metadata(
                aggregate_id=session.session_id,
                document=session.model_dump_json(by_alias=True),
                revision=session.revision,
                expected_revision=expected_revision,
                updated_at=session.updated_at,
                status=session.status.value,
            )
        except self._table.conditional_check_failed as error:
            raise SessionRevisionConflictError(
                f"session revision conflict: {session.session_id}"
            ) from error
        return self._session_from_item(attributes)

    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None:
        """Atomically advance the session counter and store exactly one event."""
        if event.sequence != expected_previous_sequence + 1:
            raise EventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        try:
            self._table.append_event(
                aggregate_id=event.session_id,
                event_item=event_item(
                    aggregate="SESSION",
                    aggregate_id=event.session_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    document=event.model_dump_json(by_alias=True),
                ),
                sequence=event.sequence,
                expected_previous_sequence=expected_previous_sequence,
            )
        except self._table.transaction_cancelled as error:
            raise EventSequenceConflictError(
                f"event sequence conflict: {event.session_id}/{event.sequence}"
            ) from error

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]:
        """Query all events after a sequence in ascending order."""
        return self._table.list_events_after(
            session_id,
            sequence,
            SessionEvent.model_validate_json,
        )

    def count_active_by_owner(self, owner_id: str) -> int:
        """Count one owner's unfinished sessions through the ``ByOwner`` index."""
        values: dict[str, AttributeValue] = {
            ":owner": string(owner_id),
            **{
                f":status{index}": string(status)
                for index, status in enumerate(_ACTIVE_STATUS_VALUES)
            },
        }
        status_placeholders = ", ".join(
            f":status{index}" for index in range(len(_ACTIVE_STATUS_VALUES))
        )
        return self._table.count_index_items(
            index_name="ByOwner",
            key_condition="ownerId = :owner",
            values=values,
            filter_expression=f"#status IN ({status_placeholders})",
            names={"#status": "status"},
        )

    def list_active_by_owner(self, owner_id: str) -> tuple[SessionRecord, ...]:
        """List one owner's live sessions via ``ByOwner``, newest ``createdAt`` first.

        The GSI has no sort key, so order is applied in process. Hard cap: 10.
        """
        values: dict[str, AttributeValue] = {
            ":owner": string(owner_id),
            **{
                f":status{index}": string(status)
                for index, status in enumerate(_ACTIVE_STATUS_VALUES)
            },
        }
        status_placeholders = ", ".join(
            f":status{index}" for index in range(len(_ACTIVE_STATUS_VALUES))
        )
        sessions = [
            self._session_from_item(item)
            for item in self._table.list_index_items(
                index_name="ByOwner",
                key_condition="ownerId = :owner",
                filter_expression=f"#status IN ({status_placeholders})",
                names={"#status": "status"},
                values=values,
            )
        ]
        sessions.sort(key=lambda session: session.created_at, reverse=True)
        return tuple(sessions[:10])

    def count_by_campaign(self, campaign_id: CampaignId) -> int:
        """Count every session forked from one campaign through the ``ByCampaign`` index."""
        return self._table.count_index_items(
            index_name="ByCampaign",
            key_condition="campaignId = :campaign",
            values={":campaign": string(campaign_id)},
        )

    @classmethod
    def _session_item(cls, session: SessionRecord) -> dict[str, AttributeValue]:
        extra = (
            {"campaignId": string(session.campaign_id)} if session.campaign_id is not None else None
        )
        return metadata_item(
            aggregate="SESSION",
            aggregate_id=session.session_id,
            aggregate_id_attr="sessionId",
            owner_id=session.owner_id,
            status=session.status.value,
            revision=session.revision,
            last_event_sequence=session.last_event_sequence,
            created_at=session.created_at,
            updated_at=session.updated_at,
            document=session.model_dump_json(by_alias=True),
            extra=extra,
        )

    @classmethod
    def _session_from_item(cls, item: Mapping[str, object]) -> SessionRecord:
        session = SessionRecord.model_validate_json(attribute_string(item, "document"))
        return session.model_copy(
            update={
                "revision": attribute_int(item, "revision"),
                "last_event_sequence": attribute_int(item, "lastEventSequence"),
            }
        )


def create_dynamodb_repository(
    table_name: str,
    *,
    region_name: str | None = None,
    idempotency_ttl_seconds: int = 86_400,
) -> DynamoDbControlPlaneRepository:
    """Create one reusable DynamoDB client and its repository adapter."""
    client = create_dynamodb_client(region_name)
    return DynamoDbControlPlaneRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
