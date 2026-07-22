from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any, TypeVar, cast

from dungeon_agent.control_plane.persistence.dynamo_types import DynamoDbClient

AttributeValue = dict[str, str]
Item = dict[str, AttributeValue]

EventT = TypeVar("EventT")


class DynamoDbAggregateStore:
    def __init__(self, client: DynamoDbClient, table_name: str, aggregate: str) -> None:
        if not table_name:
            raise ValueError("table_name must not be empty")
        self._client = client
        self._table_name = table_name
        self._aggregate = aggregate

    @property
    def transaction_cancelled(self) -> type[Exception]:
        return self._client.exceptions.TransactionCanceledException

    @property
    def conditional_check_failed(self) -> type[Exception]:
        return self._client.exceptions.ConditionalCheckFailedException

    def aggregate_pk(self, aggregate_id: str) -> str:
        return f"{self._aggregate}#{aggregate_id}"

    def get_metadata_item(self, aggregate_id: str) -> Mapping[str, object] | None:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": string(self.aggregate_pk(aggregate_id)),
                "SK": string("METADATA"),
            },
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        return raw_item if isinstance(raw_item, Mapping) else None

    def get_idempotency_id(
        self, owner_id: str, idempotency_key: str, aggregate_id_attr: str
    ) -> str | None:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": string(owner_pk(owner_id)),
                "SK": string(idempotency_sk(idempotency_key)),
            },
            ConsistentRead=True,
        )
        raw_item = response.get("Item")
        if not isinstance(raw_item, Mapping):
            return None
        return attribute_string(raw_item, aggregate_id_attr)

    def create_with_idempotency(
        self,
        *,
        aggregate_item: Item,
        owner_id: str,
        idempotency_key: str,
        aggregate_id_attr: str,
        aggregate_id: str,
        created_at: datetime,
        ttl_seconds: int,
    ) -> None:
        expires_at = int((created_at + timedelta(seconds=ttl_seconds)).timestamp())
        idempotency_item: Item = {
            "PK": string(owner_pk(owner_id)),
            "SK": string(idempotency_sk(idempotency_key)),
            "entityType": string("IDEMPOTENCY"),
            aggregate_id_attr: string(aggregate_id),
            "expiresAt": number(expires_at),
        }
        self._client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": self._table_name,
                        "Item": aggregate_item,
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

    def save_metadata(
        self,
        *,
        aggregate_id: str,
        document: str,
        revision: int,
        expected_revision: int,
        updated_at: datetime,
        status: str,
    ) -> Mapping[str, object]:
        response = self._client.update_item(
            TableName=self._table_name,
            Key={
                "PK": string(self.aggregate_pk(aggregate_id)),
                "SK": string("METADATA"),
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
                ":document": string(document),
                ":nextRevision": number(revision),
                ":expectedRevision": number(expected_revision),
                ":updatedAt": string(updated_at.isoformat()),
                ":status": string(status),
            },
            ReturnValues="ALL_NEW",
        )
        attributes = response.get("Attributes")
        if not isinstance(attributes, Mapping):
            raise RuntimeError("DynamoDB update did not return the saved aggregate")
        return attributes

    def append_event(
        self,
        *,
        aggregate_id: str,
        event_item: Item,
        sequence: int,
        expected_previous_sequence: int,
    ) -> None:
        self._client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": self._table_name,
                        "Key": {
                            "PK": string(self.aggregate_pk(aggregate_id)),
                            "SK": string("METADATA"),
                        },
                        "UpdateExpression": "SET #lastSequence = :nextSequence",
                        "ConditionExpression": "#lastSequence = :expectedSequence",
                        "ExpressionAttributeNames": {"#lastSequence": "lastEventSequence"},
                        "ExpressionAttributeValues": {
                            ":nextSequence": number(sequence),
                            ":expectedSequence": number(expected_previous_sequence),
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

    def list_events_after(
        self,
        aggregate_id: str,
        sequence: int,
        decode: Callable[[str], EventT],
    ) -> tuple[EventT, ...]:
        paginator = self._client.get_paginator("query")
        pages = paginator.paginate(
            TableName=self._table_name,
            KeyConditionExpression="PK = :pk AND SK BETWEEN :after AND :eventEnd",
            ExpressionAttributeValues={
                ":pk": string(self.aggregate_pk(aggregate_id)),
                ":after": string(f"{event_sk(sequence)}~"),
                ":eventEnd": string(event_sk(99_999_999_999_999_999_999)),
            },
            ConsistentRead=True,
            ScanIndexForward=True,
        )
        events: list[EventT] = []
        for page in pages:
            raw_items = page.get("Items", [])
            if not isinstance(raw_items, list):
                raise RuntimeError("DynamoDB query returned invalid event items")
            events.extend(
                decode(attribute_string(item, "document"))
                for item in raw_items
                if isinstance(item, Mapping)
            )
        return tuple(events)

    def count_index_items(
        self,
        *,
        index_name: str,
        key_condition: str,
        values: dict[str, AttributeValue],
        filter_expression: str | None = None,
        names: dict[str, str] | None = None,
    ) -> int:
        request = self._query_request(
            index_name=index_name,
            key_condition=key_condition,
            values=values,
            filter_expression=filter_expression,
            names=names,
        )
        request["Select"] = "COUNT"
        total = 0
        for page in self._client.get_paginator("query").paginate(**request):
            count = page.get("Count")
            if not isinstance(count, int):
                raise RuntimeError("DynamoDB count query returned an invalid page")
            total += count
        return total

    def list_index_items(
        self,
        *,
        index_name: str,
        key_condition: str,
        values: dict[str, AttributeValue],
        filter_expression: str | None = None,
        names: dict[str, str] | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        request = self._query_request(
            index_name=index_name,
            key_condition=key_condition,
            values=values,
            filter_expression=filter_expression,
            names=names,
        )
        items: list[Mapping[str, object]] = []
        for page in self._client.get_paginator("query").paginate(**request):
            raw_items = page.get("Items", [])
            if not isinstance(raw_items, list):
                raise RuntimeError("DynamoDB list query returned invalid aggregate items")
            items.extend(item for item in raw_items if isinstance(item, Mapping))
        return tuple(items)

    def _query_request(
        self,
        *,
        index_name: str,
        key_condition: str,
        values: dict[str, AttributeValue],
        filter_expression: str | None,
        names: dict[str, str] | None,
    ) -> dict[str, object]:
        request: dict[str, object] = {
            "TableName": self._table_name,
            "IndexName": index_name,
            "KeyConditionExpression": key_condition,
            "ExpressionAttributeValues": values,
        }
        if filter_expression is not None:
            request["FilterExpression"] = filter_expression
        if names is not None:
            request["ExpressionAttributeNames"] = names
        return request


class DynamoDbAggregateRepository:
    def __init__(
        self,
        client: DynamoDbClient,
        table_name: str,
        *,
        aggregate: str,
        aggregate_id_attr: str,
        record_id: Callable[[Any], str],
        event_record_id: Callable[[Any], str],
        decode_record: Callable[[Mapping[str, object]], Any],
        decode_event: Callable[[str], Any],
        already_exists_error: type[Exception],
        revision_conflict_error: type[Exception],
        sequence_conflict_error: type[Exception],
        idempotency_ttl_seconds: int,
        extra_metadata: Callable[[Any], Mapping[str, AttributeValue] | None] | None = None,
    ) -> None:
        if idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._table = DynamoDbAggregateStore(client, table_name, aggregate)
        self._aggregate = aggregate
        self._aggregate_name = aggregate.lower()
        self._aggregate_id_attr = aggregate_id_attr
        self._record_id = record_id
        self._event_record_id = event_record_id
        self._decode_record = decode_record
        self._decode_event = decode_event
        self._already_exists_error = already_exists_error
        self._revision_conflict_error = revision_conflict_error
        self._sequence_conflict_error = sequence_conflict_error
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._extra_metadata = extra_metadata

    def create(self, record: Any, idempotency_key: str) -> Any:
        aggregate_id = self._record_id(record)
        existing = self.find_by_idempotency_key(record.owner_id, idempotency_key)
        if existing is not None:
            return existing
        try:
            self._table.create_with_idempotency(
                aggregate_item=self._metadata_item(record),
                owner_id=record.owner_id,
                idempotency_key=idempotency_key,
                aggregate_id_attr=self._aggregate_id_attr,
                aggregate_id=aggregate_id,
                created_at=record.created_at,
                ttl_seconds=self._idempotency_ttl_seconds,
            )
        except self._table.transaction_cancelled as error:
            existing = self.find_by_idempotency_key(record.owner_id, idempotency_key)
            if existing is not None:
                return existing
            raise self._already_exists_error(
                f"{self._aggregate_name} or idempotency record already exists: {aggregate_id}"
            ) from error
        return record

    def get(self, aggregate_id: str) -> Any | None:
        item = self._table.get_metadata_item(aggregate_id)
        return None if item is None else self._decode_record(item)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> Any | None:
        aggregate_id = self._table.get_idempotency_id(
            owner_id, idempotency_key, self._aggregate_id_attr
        )
        return None if aggregate_id is None else self.get(aggregate_id)

    def save(self, record: Any, *, expected_revision: int) -> Any:
        aggregate_id = self._record_id(record)
        if record.revision != expected_revision + 1:
            raise self._revision_conflict_error(
                f"saved {self._aggregate_name} revision must be exactly one greater "
                "than expected revision"
            )
        try:
            attributes = self._table.save_metadata(
                aggregate_id=aggregate_id,
                document=record.model_dump_json(by_alias=True),
                revision=record.revision,
                expected_revision=expected_revision,
                updated_at=record.updated_at,
                status=record.status.value,
            )
        except self._table.conditional_check_failed as error:
            raise self._revision_conflict_error(
                f"{self._aggregate_name} revision conflict: {aggregate_id}"
            ) from error
        return self._decode_record(attributes)

    def append(self, event: Any, *, expected_previous_sequence: int) -> None:
        aggregate_id = self._event_record_id(event)
        if event.sequence != expected_previous_sequence + 1:
            raise self._sequence_conflict_error(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        try:
            self._table.append_event(
                aggregate_id=aggregate_id,
                event_item=event_item(
                    aggregate=self._aggregate,
                    aggregate_id=aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    document=event.model_dump_json(by_alias=True),
                ),
                sequence=event.sequence,
                expected_previous_sequence=expected_previous_sequence,
            )
        except self._table.transaction_cancelled as error:
            raise self._sequence_conflict_error(
                f"event sequence conflict: {aggregate_id}/{event.sequence}"
            ) from error

    def list_after(self, aggregate_id: str, sequence: int) -> tuple[Any, ...]:
        return self._table.list_events_after(aggregate_id, sequence, self._decode_event)

    def _metadata_item(self, record: Any) -> Item:
        aggregate_id = self._record_id(record)
        return metadata_item(
            aggregate=self._aggregate,
            aggregate_id=aggregate_id,
            aggregate_id_attr=self._aggregate_id_attr,
            owner_id=record.owner_id,
            status=record.status.value,
            revision=record.revision,
            last_event_sequence=record.last_event_sequence,
            created_at=record.created_at,
            updated_at=record.updated_at,
            document=record.model_dump_json(by_alias=True),
            extra=None if self._extra_metadata is None else self._extra_metadata(record),
        )


def metadata_item(
    *,
    aggregate: str,
    aggregate_id: str,
    aggregate_id_attr: str,
    owner_id: str,
    status: str,
    revision: int,
    last_event_sequence: int,
    created_at: datetime,
    updated_at: datetime,
    document: str,
    extra: Mapping[str, AttributeValue] | None = None,
) -> Item:
    item: Item = {
        "PK": string(f"{aggregate}#{aggregate_id}"),
        "SK": string("METADATA"),
        "entityType": string(aggregate),
        aggregate_id_attr: string(aggregate_id),
        "ownerId": string(owner_id),
        "status": string(status),
        "revision": number(revision),
        "lastEventSequence": number(last_event_sequence),
        "createdAt": string(created_at.isoformat()),
        "updatedAt": string(updated_at.isoformat()),
        "document": string(document),
    }
    if extra is not None:
        item.update(extra)
    return item


def event_item(
    *,
    aggregate: str,
    aggregate_id: str,
    sequence: int,
    occurred_at: datetime,
    document: str,
) -> Item:
    return {
        "PK": string(f"{aggregate}#{aggregate_id}"),
        "SK": string(event_sk(sequence)),
        "entityType": string("EVENT"),
        "sequence": number(sequence),
        "occurredAt": string(occurred_at.isoformat()),
        "document": string(document),
    }


def attribute_string(item: Mapping[str, object], name: str) -> str:
    value = item.get(name)
    raw = value.get("S") if isinstance(value, Mapping) else None
    if not isinstance(raw, str):
        raise RuntimeError(f"DynamoDB item is missing string attribute {name}")
    return raw


def attribute_int(item: Mapping[str, object], name: str) -> int:
    value = item.get(name)
    raw = value.get("N") if isinstance(value, Mapping) else None
    if not isinstance(raw, str):
        raise RuntimeError(f"DynamoDB item is missing number attribute {name}")
    return int(raw)


def string(value: str) -> AttributeValue:
    return {"S": value}


def number(value: int) -> AttributeValue:
    return {"N": str(value)}


def owner_pk(owner_id: str) -> str:
    return f"OWNER#{owner_id}"


def idempotency_sk(idempotency_key: str) -> str:
    return f"IDEMPOTENCY#{idempotency_key}"


def event_sk(sequence: int) -> str:
    return f"EVENT#{sequence:020d}"


def create_dynamodb_client(region_name: str | None = None) -> DynamoDbClient:
    config_cls = cast(Any, import_module("botocore.config")).Config
    boto3 = cast(Any, import_module("boto3"))
    config = config_cls(
        retries={"total_max_attempts": 3, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    )
    return cast(
        DynamoDbClient,
        boto3.client("dynamodb", region_name=region_name, config=config),
    )
