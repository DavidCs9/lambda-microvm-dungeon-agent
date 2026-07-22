"""DynamoDB single-table adapter for sessions, idempotency, and ordered events."""

from collections.abc import Mapping
from datetime import timedelta
from importlib import import_module
from typing import Any, cast

from dungeon_agent.control_plane.domain.enums import SessionStatus
from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    SessionEvent,
    SessionId,
    SessionRecord,
)
from dungeon_agent.control_plane.persistence.dynamo_types import DynamoDbClient
from dungeon_agent.control_plane.persistence.errors import (
    EventSequenceConflictError,
    SessionAlreadyExistsError,
    SessionRevisionConflictError,
)

AttributeValue = dict[str, str]
Item = dict[str, AttributeValue]

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
        self._client = client
        self._table_name = table_name
        self._idempotency_ttl_seconds = idempotency_ttl_seconds

    def create(self, session: SessionRecord, idempotency_key: str) -> SessionRecord:
        """Atomically persist a session and its owner-scoped idempotency record."""
        existing = self.find_by_idempotency_key(session.owner_id, idempotency_key)
        if existing is not None:
            return existing

        session_item = self._session_item(session)
        expires_at = int(
            (session.created_at + timedelta(seconds=self._idempotency_ttl_seconds)).timestamp()
        )
        idempotency_item: Item = {
            "PK": self._string(self._owner_pk(session.owner_id)),
            "SK": self._string(self._idempotency_sk(idempotency_key)),
            "entityType": self._string("IDEMPOTENCY"),
            "sessionId": self._string(session.session_id),
            "expiresAt": self._number(expires_at),
        }
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": session_item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": idempotency_item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
        except self._client.exceptions.TransactionCanceledException as error:
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
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": self._string(self._session_pk(session_id)),
                "SK": self._string("METADATA"),
            },
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        if not isinstance(raw_item, Mapping):
            return None
        return self._session_from_item(raw_item)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> SessionRecord | None:
        """Resolve an owner-scoped idempotency key to its original session."""
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": self._string(self._owner_pk(owner_id)),
                "SK": self._string(self._idempotency_sk(idempotency_key)),
            },
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        if not isinstance(raw_item, Mapping):
            return None
        session_id = self._attribute_string(raw_item, "sessionId")
        return self.get(session_id)

    def save(self, session: SessionRecord, *, expected_revision: int) -> SessionRecord:
        """Save one state revision without overwriting the independent event counter."""
        if session.revision != expected_revision + 1:
            raise SessionRevisionConflictError(
                "saved session revision must be exactly one greater than expected revision"
            )
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={
                    "PK": self._string(self._session_pk(session.session_id)),
                    "SK": self._string("METADATA"),
                },
                UpdateExpression=(
                    "SET #document = :document, #revision = :nextRevision, "
                    "#updatedAt = :updatedAt, #status = :status"
                ),
                ConditionExpression="#revision = :expectedRevision",
                ExpressionAttributeNames={
                    "#document": "document",
                    "#revision": "revision",
                    "#updatedAt": "updatedAt",
                    "#status": "status",
                },
                ExpressionAttributeValues={
                    ":document": self._string(session.model_dump_json(by_alias=True)),
                    ":nextRevision": self._number(session.revision),
                    ":expectedRevision": self._number(expected_revision),
                    ":updatedAt": self._string(session.updated_at.isoformat()),
                    ":status": self._string(session.status.value),
                },
                ReturnValues="ALL_NEW",
            )
        except self._client.exceptions.ConditionalCheckFailedException as error:
            raise SessionRevisionConflictError(
                f"session revision conflict: {session.session_id}"
            ) from error
        attributes = response.get("Attributes")
        if not isinstance(attributes, Mapping):
            raise RuntimeError("DynamoDB update did not return the saved session")
        return self._session_from_item(attributes)

    def append(self, event: SessionEvent, *, expected_previous_sequence: int) -> None:
        """Atomically advance the session counter and store exactly one event."""
        if event.sequence != expected_previous_sequence + 1:
            raise EventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        event_item: Item = {
            "PK": self._string(self._session_pk(event.session_id)),
            "SK": self._string(self._event_sk(event.sequence)),
            "entityType": self._string("EVENT"),
            "sequence": self._number(event.sequence),
            "occurredAt": self._string(event.occurred_at.isoformat()),
            "document": self._string(event.model_dump_json(by_alias=True)),
        }
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self._table_name,
                            "Key": {
                                "PK": self._string(self._session_pk(event.session_id)),
                                "SK": self._string("METADATA"),
                            },
                            "UpdateExpression": "SET #lastSequence = :nextSequence",
                            "ConditionExpression": "#lastSequence = :expectedSequence",
                            "ExpressionAttributeNames": {"#lastSequence": "lastEventSequence"},
                            "ExpressionAttributeValues": {
                                ":nextSequence": self._number(event.sequence),
                                ":expectedSequence": self._number(expected_previous_sequence),
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": event_item,
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
        except self._client.exceptions.TransactionCanceledException as error:
            raise EventSequenceConflictError(
                f"event sequence conflict: {event.session_id}/{event.sequence}"
            ) from error

    def list_after(self, session_id: SessionId, sequence: int) -> tuple[SessionEvent, ...]:
        """Query all events after a sequence in ascending order."""
        paginator = self._client.get_paginator("query")
        pages = paginator.paginate(
            TableName=self._table_name,
            KeyConditionExpression="PK = :pk AND SK BETWEEN :after AND :eventEnd",
            ExpressionAttributeValues={
                ":pk": self._string(self._session_pk(session_id)),
                # Appending a suffix makes the lower bound exclusive for the exact
                # sequence while retaining a single DynamoDB key condition.
                ":after": self._string(f"{self._event_sk(sequence)}~"),
                ":eventEnd": self._string(self._event_sk(99_999_999_999_999_999_999)),
            },
            ConsistentRead=True,
            ScanIndexForward=True,
        )
        events: list[SessionEvent] = []
        for page in pages:
            raw_items = page.get("Items", [])
            if not isinstance(raw_items, list):
                raise RuntimeError("DynamoDB query returned invalid event items")
            events.extend(
                SessionEvent.model_validate_json(self._attribute_string(item, "document"))
                for item in raw_items
                if isinstance(item, Mapping)
            )
        return tuple(events)

    def count_active_by_owner(self, owner_id: str) -> int:
        """Count one owner's unfinished sessions through the ``ByOwner`` index."""
        values: dict[str, AttributeValue] = {
            ":owner": self._string(owner_id),
            **{
                f":status{index}": self._string(status)
                for index, status in enumerate(_ACTIVE_STATUS_VALUES)
            },
        }
        status_placeholders = ", ".join(
            f":status{index}" for index in range(len(_ACTIVE_STATUS_VALUES))
        )
        return self._count_index_items(
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
            ":owner": self._string(owner_id),
            **{
                f":status{index}": self._string(status)
                for index, status in enumerate(_ACTIVE_STATUS_VALUES)
            },
        }
        status_placeholders = ", ".join(
            f":status{index}" for index in range(len(_ACTIVE_STATUS_VALUES))
        )
        paginator = self._client.get_paginator("query")
        sessions: list[SessionRecord] = []
        for page in paginator.paginate(
            TableName=self._table_name,
            IndexName="ByOwner",
            KeyConditionExpression="ownerId = :owner",
            FilterExpression=f"#status IN ({status_placeholders})",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=values,
        ):
            raw_items = page.get("Items", [])
            if not isinstance(raw_items, list):
                raise RuntimeError("DynamoDB list query returned invalid session items")
            sessions.extend(
                self._session_from_item(item) for item in raw_items if isinstance(item, Mapping)
            )
        sessions.sort(key=lambda session: session.created_at, reverse=True)
        return tuple(sessions[:10])

    def count_by_campaign(self, campaign_id: CampaignId) -> int:
        """Count every session forked from one campaign through the ``ByCampaign`` index."""
        return self._count_index_items(
            index_name="ByCampaign",
            key_condition="campaignId = :campaign",
            values={":campaign": self._string(campaign_id)},
        )

    def _count_index_items(
        self,
        *,
        index_name: str,
        key_condition: str,
        values: dict[str, AttributeValue],
        filter_expression: str | None = None,
        names: dict[str, str] | None = None,
    ) -> int:
        paginator = self._client.get_paginator("query")
        request: dict[str, object] = {
            "TableName": self._table_name,
            "IndexName": index_name,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeValues": values,
            "Select": "COUNT",
        }
        if filter_expression is not None:
            request["FilterExpression"] = filter_expression
        if names is not None:
            request["ExpressionAttributeNames"] = names
        total = 0
        for page in paginator.paginate(**request):
            count = page.get("Count")
            if not isinstance(count, int):
                raise RuntimeError("DynamoDB count query returned an invalid page")
            total += count
        return total

    @classmethod
    def _session_item(cls, session: SessionRecord) -> Item:
        item: Item = {
            "PK": cls._string(cls._session_pk(session.session_id)),
            "SK": cls._string("METADATA"),
            "entityType": cls._string("SESSION"),
            "sessionId": cls._string(session.session_id),
            "ownerId": cls._string(session.owner_id),
            "status": cls._string(session.status.value),
            "revision": cls._number(session.revision),
            "lastEventSequence": cls._number(session.last_event_sequence),
            "createdAt": cls._string(session.created_at.isoformat()),
            "updatedAt": cls._string(session.updated_at.isoformat()),
            "document": cls._string(session.model_dump_json(by_alias=True)),
        }
        if session.campaign_id is not None:
            item["campaignId"] = cls._string(session.campaign_id)
        return item

    @classmethod
    def _session_from_item(cls, item: Mapping[str, object]) -> SessionRecord:
        session = SessionRecord.model_validate_json(cls._attribute_string(item, "document"))
        return session.model_copy(
            update={
                "revision": cls._attribute_int(item, "revision"),
                "last_event_sequence": cls._attribute_int(item, "lastEventSequence"),
            }
        )

    @staticmethod
    def _attribute_string(item: Mapping[str, object], name: str) -> str:
        value = item.get(name)
        raw = value.get("S") if isinstance(value, Mapping) else None
        if not isinstance(raw, str):
            raise RuntimeError(f"DynamoDB item is missing string attribute {name}")
        return raw

    @staticmethod
    def _attribute_int(item: Mapping[str, object], name: str) -> int:
        value = item.get(name)
        raw = value.get("N") if isinstance(value, Mapping) else None
        if not isinstance(raw, str):
            raise RuntimeError(f"DynamoDB item is missing number attribute {name}")
        return int(raw)

    @staticmethod
    def _string(value: str) -> AttributeValue:
        return {"S": value}

    @staticmethod
    def _number(value: int) -> AttributeValue:
        return {"N": str(value)}

    @staticmethod
    def _session_pk(session_id: str) -> str:
        return f"SESSION#{session_id}"

    @staticmethod
    def _owner_pk(owner_id: str) -> str:
        return f"OWNER#{owner_id}"

    @staticmethod
    def _idempotency_sk(idempotency_key: str) -> str:
        return f"IDEMPOTENCY#{idempotency_key}"

    @staticmethod
    def _event_sk(sequence: int) -> str:
        return f"EVENT#{sequence:020d}"


def create_dynamodb_repository(
    table_name: str,
    *,
    region_name: str | None = None,
    idempotency_ttl_seconds: int = 86_400,
) -> DynamoDbControlPlaneRepository:
    """Create one reusable DynamoDB client and its repository adapter."""
    config_cls = cast(Any, import_module("botocore.config")).Config
    boto3 = cast(Any, import_module("boto3"))
    config = config_cls(
        retries={"total_max_attempts": 3, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    )
    client = cast(
        DynamoDbClient,
        boto3.client("dynamodb", region_name=region_name, config=config),
    )
    return DynamoDbControlPlaneRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
