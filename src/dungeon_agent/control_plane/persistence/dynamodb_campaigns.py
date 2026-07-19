"""DynamoDB single-table adapter for campaigns and their ordered events."""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Protocol, cast

import boto3
from botocore.config import Config

from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignId,
    CampaignRecord,
)
from dungeon_agent.control_plane.persistence.errors import (
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
)

AttributeValue = dict[str, str]
Item = dict[str, AttributeValue]


class _DynamoDbExceptions(Protocol):
    ConditionalCheckFailedException: type[Exception]
    TransactionCanceledException: type[Exception]


class _QueryPaginator(Protocol):
    def paginate(self, **kwargs: object) -> Iterable[Mapping[str, object]]: ...


class _DynamoDbClient(Protocol):
    @property
    def exceptions(self) -> _DynamoDbExceptions: ...

    def get_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def update_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def transact_write_items(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_paginator(self, operation_name: str) -> _QueryPaginator: ...


class DynamoDbCampaignRepository:
    """Implement campaign and campaign-event ports with a single-table layout.

    Access patterns:

    - ``PK=CAMPAIGN#{id}, SK=METADATA`` stores the campaign.
    - ``PK=CAMPAIGN#{id}, SK=EVENT#{sequence}`` stores ordered events.
    - ``PK=OWNER#{owner}, SK=IDEMPOTENCY#{key}`` maps duplicate creates.
    - the ``ByOwner`` index on ``ownerId`` counts one owner's campaigns.
    """

    def __init__(
        self,
        client: _DynamoDbClient,
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

    def create(self, campaign: CampaignRecord, idempotency_key: str) -> CampaignRecord:
        """Atomically persist a campaign and its owner-scoped idempotency record."""
        existing = self.find_by_idempotency_key(campaign.owner_id, idempotency_key)
        if existing is not None:
            return existing

        campaign_item = self._campaign_item(campaign)
        expires_at = int(
            (campaign.created_at + timedelta(seconds=self._idempotency_ttl_seconds)).timestamp()
        )
        idempotency_item: Item = {
            "PK": self._string(self._owner_pk(campaign.owner_id)),
            "SK": self._string(self._idempotency_sk(idempotency_key)),
            "entityType": self._string("IDEMPOTENCY"),
            "campaignId": self._string(campaign.campaign_id),
            "expiresAt": self._number(expires_at),
        }
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": campaign_item,
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
            existing = self.find_by_idempotency_key(campaign.owner_id, idempotency_key)
            if existing is not None:
                return existing
            raise CampaignAlreadyExistsError(
                f"campaign or idempotency record already exists: {campaign.campaign_id}"
            ) from error
        return campaign

    def get(self, campaign_id: CampaignId) -> CampaignRecord | None:
        """Read a campaign consistently so revision checks see recent writes."""
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": self._string(self._campaign_pk(campaign_id)),
                "SK": self._string("METADATA"),
            },
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        if not isinstance(raw_item, Mapping):
            return None
        return self._campaign_from_item(raw_item)

    def find_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> CampaignRecord | None:
        """Resolve an owner-scoped idempotency key to its original campaign."""
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
        campaign_id = self._attribute_string(raw_item, "campaignId")
        return self.get(campaign_id)

    def save(self, campaign: CampaignRecord, *, expected_revision: int) -> CampaignRecord:
        """Save one state revision without overwriting the independent event counter."""
        if campaign.revision != expected_revision + 1:
            raise CampaignRevisionConflictError(
                "saved campaign revision must be exactly one greater than expected revision"
            )
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={
                    "PK": self._string(self._campaign_pk(campaign.campaign_id)),
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
                    ":document": self._string(campaign.model_dump_json(by_alias=True)),
                    ":nextRevision": self._number(campaign.revision),
                    ":expectedRevision": self._number(expected_revision),
                    ":updatedAt": self._string(campaign.updated_at.isoformat()),
                    ":status": self._string(campaign.status.value),
                },
                ReturnValues="ALL_NEW",
            )
        except self._client.exceptions.ConditionalCheckFailedException as error:
            raise CampaignRevisionConflictError(
                f"campaign revision conflict: {campaign.campaign_id}"
            ) from error
        attributes = response.get("Attributes")
        if not isinstance(attributes, Mapping):
            raise RuntimeError("DynamoDB update did not return the saved campaign")
        return self._campaign_from_item(attributes)

    def append(self, event: CampaignEvent, *, expected_previous_sequence: int) -> None:
        """Atomically advance the campaign counter and store exactly one event."""
        if event.sequence != expected_previous_sequence + 1:
            raise CampaignEventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        event_item: Item = {
            "PK": self._string(self._campaign_pk(event.campaign_id)),
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
                                "PK": self._string(self._campaign_pk(event.campaign_id)),
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
            raise CampaignEventSequenceConflictError(
                f"event sequence conflict: {event.campaign_id}/{event.sequence}"
            ) from error

    def list_after(self, campaign_id: CampaignId, sequence: int) -> tuple[CampaignEvent, ...]:
        """Query all events after a sequence in ascending order."""
        paginator = self._client.get_paginator("query")
        pages = paginator.paginate(
            TableName=self._table_name,
            KeyConditionExpression="PK = :pk AND SK BETWEEN :after AND :eventEnd",
            ExpressionAttributeValues={
                ":pk": self._string(self._campaign_pk(campaign_id)),
                ":after": self._string(f"{self._event_sk(sequence)}~"),
                ":eventEnd": self._string(self._event_sk(99_999_999_999_999_999_999)),
            },
            ConsistentRead=True,
            ScanIndexForward=True,
        )
        events: list[CampaignEvent] = []
        for page in pages:
            raw_items = page.get("Items", [])
            if not isinstance(raw_items, list):
                raise RuntimeError("DynamoDB query returned invalid event items")
            events.extend(
                CampaignEvent.model_validate_json(self._attribute_string(item, "document"))
                for item in raw_items
                if isinstance(item, Mapping)
            )
        return tuple(events)

    def count_by_owner(self, owner_id: str) -> int:
        """Count every campaign one owner has created through the ``ByOwner`` index."""
        paginator = self._client.get_paginator("query")
        total = 0
        for page in paginator.paginate(
            TableName=self._table_name,
            IndexName="ByOwner",
            KeyConditionExpression="ownerId = :owner",
            ExpressionAttributeValues={":owner": self._string(owner_id)},
            Select="COUNT",
        ):
            count = page.get("Count")
            if not isinstance(count, int):
                raise RuntimeError("DynamoDB count query returned an invalid page")
            total += count
        return total

    @classmethod
    def _campaign_item(cls, campaign: CampaignRecord) -> Item:
        return {
            "PK": cls._string(cls._campaign_pk(campaign.campaign_id)),
            "SK": cls._string("METADATA"),
            "entityType": cls._string("CAMPAIGN"),
            "campaignId": cls._string(campaign.campaign_id),
            "ownerId": cls._string(campaign.owner_id),
            "status": cls._string(campaign.status.value),
            "revision": cls._number(campaign.revision),
            "lastEventSequence": cls._number(campaign.last_event_sequence),
            "createdAt": cls._string(campaign.created_at.isoformat()),
            "updatedAt": cls._string(campaign.updated_at.isoformat()),
            "document": cls._string(campaign.model_dump_json(by_alias=True)),
        }

    @classmethod
    def _campaign_from_item(cls, item: Mapping[str, object]) -> CampaignRecord:
        campaign = CampaignRecord.model_validate_json(cls._attribute_string(item, "document"))
        return campaign.model_copy(
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
    def _campaign_pk(campaign_id: str) -> str:
        return f"CAMPAIGN#{campaign_id}"

    @staticmethod
    def _owner_pk(owner_id: str) -> str:
        return f"OWNER#{owner_id}"

    @staticmethod
    def _idempotency_sk(idempotency_key: str) -> str:
        return f"IDEMPOTENCY#{idempotency_key}"

    @staticmethod
    def _event_sk(sequence: int) -> str:
        return f"EVENT#{sequence:020d}"


def create_dynamodb_campaign_repository(
    table_name: str,
    *,
    region_name: str | None = None,
    idempotency_ttl_seconds: int = 86_400,
) -> DynamoDbCampaignRepository:
    """Create one reusable DynamoDB client and its campaign repository adapter."""
    config = Config(
        retries={"total_max_attempts": 3, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    )
    client = cast(
        _DynamoDbClient,
        boto3.client("dynamodb", region_name=region_name, config=config),
    )
    return DynamoDbCampaignRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
