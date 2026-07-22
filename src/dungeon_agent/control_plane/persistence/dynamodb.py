from collections.abc import Mapping

from dungeon_agent.control_plane.domain.enums import ACTIVE_SESSION_STATUSES
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    SessionEvent,
    SessionRecord,
)
from dungeon_agent.control_plane.persistence.dynamo_helpers import (
    AttributeValue,
    DynamoDbAggregateRepository,
    attribute_int,
    attribute_string,
    create_dynamodb_client,
    string,
)
from dungeon_agent.control_plane.persistence.dynamo_types import DynamoDbClient
from dungeon_agent.control_plane.persistence.errors import (
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)

_ACTIVE_STATUS_VALUES = tuple(status.value for status in ACTIVE_SESSION_STATUSES)
_ACTIVE_STATUS_PLACEHOLDERS = ", ".join(
    f":status{index}" for index in range(len(_ACTIVE_STATUS_VALUES))
)


class DynamoDbControlPlaneRepository(DynamoDbAggregateRepository):
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
        super().__init__(
            client,
            table_name,
            aggregate="SESSION",
            aggregate_id_attr="sessionId",
            already_exists_error=SessionAlreadyExistsError,
            revision_conflict_error=SessionRevisionConflictError,
            sequence_conflict_error=EventSequenceConflictError,
            record_id=lambda session: session.session_id,
            event_record_id=lambda event: event.session_id,
            decode_record=self._session_from_item,
            decode_event=SessionEvent.model_validate_json,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
            extra_metadata=_session_extra,
        )

    def count_active_by_owner(self, owner_id: str) -> int:
        values = _active_status_values(owner_id)
        return self._table.count_index_items(
            index_name="ByOwner",
            key_condition="ownerId = :owner",
            values=values,
            filter_expression=f"#status IN ({_ACTIVE_STATUS_PLACEHOLDERS})",
            names={"#status": "status"},
        )

    def list_active_by_owner(self, owner_id: str) -> tuple[SessionRecord, ...]:
        """List one owner's live sessions via ``ByOwner``, newest ``createdAt`` first.

        The GSI has no sort key, so order is applied in process. Hard cap: 10.
        """
        values = _active_status_values(owner_id)
        sessions = [
            self._session_from_item(item)
            for item in self._table.list_index_items(
                index_name="ByOwner",
                key_condition="ownerId = :owner",
                filter_expression=f"#status IN ({_ACTIVE_STATUS_PLACEHOLDERS})",
                names={"#status": "status"},
                values=values,
            )
        ]
        sessions.sort(key=lambda session: session.created_at, reverse=True)
        return tuple(sessions[:10])

    def count_by_campaign(self, campaign_id: CampaignId) -> int:
        return self._table.count_index_items(
            index_name="ByCampaign",
            key_condition="campaignId = :campaign",
            values={":campaign": string(campaign_id)},
        )

    @staticmethod
    def _session_from_item(item: Mapping[str, object]) -> SessionRecord:
        session = SessionRecord.model_validate_json(attribute_string(item, "document"))
        return session.model_copy(
            update={
                "revision": attribute_int(item, "revision"),
                "last_event_sequence": attribute_int(item, "lastEventSequence"),
            }
        )


def _active_status_values(owner_id: str) -> dict[str, AttributeValue]:
    return {
        ":owner": string(owner_id),
        **{f":status{index}": string(status) for index, status in enumerate(_ACTIVE_STATUS_VALUES)},
    }


def _session_extra(session: SessionRecord) -> dict[str, AttributeValue] | None:
    return {"campaignId": string(session.campaign_id)} if session.campaign_id is not None else None


def create_dynamodb_repository(
    table_name: str,
    *,
    region_name: str | None = None,
    idempotency_ttl_seconds: int = 86_400,
) -> DynamoDbControlPlaneRepository:
    client = create_dynamodb_client(region_name)
    return DynamoDbControlPlaneRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
