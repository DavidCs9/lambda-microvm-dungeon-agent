# ruff: noqa: E501
from collections.abc import Callable, Mapping
from datetime import timedelta
from importlib import import_module
from typing import Any, cast

from dungeon_agent.aws.dynamo_types import DynamoDbClient

AttributeValue = dict[str, str]
Item = dict[str, AttributeValue]


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
        if not table_name:
            raise ValueError("table_name must not be empty")
        if idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._client, self._table, self._table_name = client, self, table_name
        self._aggregate, self._aggregate_name, self._aggregate_id_attr = (
            aggregate,
            aggregate.lower(),
            aggregate_id_attr,
        )
        self._record_id, self._event_record_id = record_id, event_record_id
        self._decode_record, self._decode_event = decode_record, decode_event
        self._already_exists_error = already_exists_error
        self._revision_conflict_error, self._sequence_conflict_error = (
            revision_conflict_error,
            sequence_conflict_error,
        )
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._extra_metadata = extra_metadata

    @property
    def transaction_cancelled(self) -> type[Exception]:
        return self._client.exceptions.TransactionCanceledException

    @property
    def conditional_check_failed(self) -> type[Exception]:
        return self._client.exceptions.ConditionalCheckFailedException

    def create(self, record: Any, idempotency_key: str) -> Any:
        aggregate_id = self._record_id(record)
        existing = self.find_by_idempotency_key(record.owner_id, idempotency_key)
        if existing is not None:
            return existing
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": self._metadata_item(record),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": self._idempotency_item(record, idempotency_key),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
        except self.transaction_cancelled as error:
            existing = self.find_by_idempotency_key(record.owner_id, idempotency_key)
            if existing is not None:
                return existing
            raise self._already_exists_error(
                f"{self._aggregate_name} or idempotency record already exists: {aggregate_id}"
            ) from error
        return record

    def get(self, aggregate_id: str) -> Any | None:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={"PK": string(self._pk(aggregate_id)), "SK": string("METADATA")},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return self._decode_record(item) if isinstance(item, Mapping) else None

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> Any | None:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={"PK": string(f"OWNER#{owner_id}"), "SK": string(f"IDEMPOTENCY#{idempotency_key}")},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not isinstance(item, Mapping):
            return None
        return self.get(attribute_string(item, self._aggregate_id_attr))

    def save(self, record: Any, *, expected_revision: int) -> Any:
        aggregate_id = self._record_id(record)
        if record.revision != expected_revision + 1:
            raise self._revision_conflict_error(
                f"saved {self._aggregate_name} revision must be exactly one greater "
                "than expected revision"
            )
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={"PK": string(self._pk(aggregate_id)), "SK": string("METADATA")},
                UpdateExpression="SET #document = :document, #revision = :nextRevision, #updatedAt = :updatedAt, #status = :status",
                ConditionExpression="#revision = :expectedRevision",
                ExpressionAttributeNames={
                    "#document": "document",
                    "#revision": "revision",
                    "#updatedAt": "updatedAt",
                    "#status": "status",
                },
                ExpressionAttributeValues={
                    ":document": string(record.model_dump_json(by_alias=True)),
                    ":nextRevision": number(record.revision),
                    ":expectedRevision": number(expected_revision),
                    ":updatedAt": string(record.updated_at.isoformat()),
                    ":status": string(record.status.value),
                },
                ReturnValues="ALL_NEW",
            )
        except self.conditional_check_failed as error:
            raise self._revision_conflict_error(
                f"{self._aggregate_name} revision conflict: {aggregate_id}"
            ) from error
        attributes = response.get("Attributes")
        if not isinstance(attributes, Mapping):
            raise RuntimeError("DynamoDB update did not return the saved aggregate")
        return self._decode_record(attributes)

    def append(self, event: Any, *, expected_previous_sequence: int) -> None:
        aggregate_id = self._event_record_id(event)
        if event.sequence != expected_previous_sequence + 1:
            raise self._sequence_conflict_error(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self._table_name,
                            "Key": {"PK": string(self._pk(aggregate_id)), "SK": string("METADATA")},
                            "UpdateExpression": "SET #lastSequence = :nextSequence",
                            "ConditionExpression": "#lastSequence = :expectedSequence",
                            "ExpressionAttributeNames": {"#lastSequence": "lastEventSequence"},
                            "ExpressionAttributeValues": {
                                ":nextSequence": number(event.sequence),
                                ":expectedSequence": number(expected_previous_sequence),
                            },
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table_name,
                            "Item": {
                                "PK": string(self._pk(aggregate_id)),
                                "SK": string(f"EVENT#{event.sequence:020d}"),
                                "entityType": string("EVENT"),
                                "sequence": number(event.sequence),
                                "occurredAt": string(event.occurred_at.isoformat()),
                                "document": string(event.model_dump_json(by_alias=True)),
                            },
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
        except self.transaction_cancelled as error:
            raise self._sequence_conflict_error(
                f"event sequence conflict: {aggregate_id}/{event.sequence}"
            ) from error

    def list_after(self, aggregate_id: str, sequence: int) -> tuple[Any, ...]:
        events: list[Any] = []
        for page in self._client.get_paginator("query").paginate(
            TableName=self._table_name,
            KeyConditionExpression="PK = :pk AND SK BETWEEN :after AND :eventEnd",
            ExpressionAttributeValues={
                ":pk": string(self._pk(aggregate_id)),
                ":after": string(f"EVENT#{sequence:020d}~"),
                ":eventEnd": string("EVENT#99999999999999999999"),
            },
            ConsistentRead=True,
            ScanIndexForward=True,
        ):
            items = page.get("Items", [])
            if not isinstance(items, list):
                raise RuntimeError("DynamoDB query returned invalid event items")
            events.extend(
                self._decode_event(attribute_string(item, "document"))
                for item in items
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
        request = self._query_request(index_name, key_condition, values, filter_expression, names)
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
        request = self._query_request(index_name, key_condition, values, filter_expression, names)
        found: list[Mapping[str, object]] = []
        for page in self._client.get_paginator("query").paginate(**request):
            items = page.get("Items", [])
            if not isinstance(items, list):
                raise RuntimeError("DynamoDB list query returned invalid aggregate items")
            found.extend(item for item in items if isinstance(item, Mapping))
        return tuple(found)

    def _query_request(
        self,
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

    def _metadata_item(self, record: Any) -> Item:
        aggregate_id = self._record_id(record)
        item: Item = {
            "PK": string(self._pk(aggregate_id)),
            "SK": string("METADATA"),
            "entityType": string(self._aggregate),
            self._aggregate_id_attr: string(aggregate_id),
            "ownerId": string(record.owner_id),
            "status": string(record.status.value),
            "revision": number(record.revision),
            "lastEventSequence": number(record.last_event_sequence),
            "createdAt": string(record.created_at.isoformat()),
            "updatedAt": string(record.updated_at.isoformat()),
            "document": string(record.model_dump_json(by_alias=True)),
        }
        extra = None if self._extra_metadata is None else self._extra_metadata(record)
        if extra is not None:
            item.update(extra)
        return item

    def _idempotency_item(self, record: Any, idempotency_key: str) -> Item:
        expires_at = int(
            (record.created_at + timedelta(seconds=self._idempotency_ttl_seconds)).timestamp()
        )
        return {
            "PK": string(f"OWNER#{record.owner_id}"),
            "SK": string(f"IDEMPOTENCY#{idempotency_key}"),
            "entityType": string("IDEMPOTENCY"),
            self._aggregate_id_attr: string(self._record_id(record)),
            "expiresAt": number(expires_at),
        }

    def _pk(self, aggregate_id: str) -> str:
        return f"{self._aggregate}#{aggregate_id}"


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


def create_dynamodb_client(region_name: str | None = None) -> DynamoDbClient:
    config_cls = cast(Any, import_module("botocore.config")).Config
    boto3 = cast(Any, import_module("boto3"))
    config = config_cls(
        retries={"total_max_attempts": 3, "mode": "adaptive"}, connect_timeout=3, read_timeout=10
    )
    return cast(DynamoDbClient, boto3.client("dynamodb", region_name=region_name, config=config))
