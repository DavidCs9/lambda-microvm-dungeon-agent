"""DynamoDB connection records with TTL and session subscriptions."""

from collections.abc import Mapping
from typing import Protocol

from boto3.dynamodb.conditions import Key

from dungeon_agent.control_plane.domain.models import SessionId
from dungeon_agent.control_plane.realtime.models import ConnectionRecord


class DynamoTable(Protocol):
    def put_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def update_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def delete_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def query(self, **kwargs: object) -> Mapping[str, object]: ...


class DynamoDbConnectionRepository:
    def __init__(self, table: DynamoTable) -> None:
        self._table = table

    def put(self, connection: ConnectionRecord) -> None:
        self._table.put_item(Item=self._connection_item(connection))

    def get(self, connection_id: str) -> ConnectionRecord | None:
        response = self._table.get_item(
            Key={"PK": self._connection_pk(connection_id), "SK": "METADATA"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not isinstance(item, Mapping):
            return None
        document = item.get("document")
        if not isinstance(document, str):
            raise RuntimeError("connection item is missing its document")
        return ConnectionRecord.model_validate_json(document)

    def subscribe(self, connection: ConnectionRecord) -> None:
        if connection.session_id is None:
            raise ValueError("a subscription requires a session_id")
        previous = self.get(connection.connection_id)
        if previous is not None and previous.session_id not in {None, connection.session_id}:
            self._delete_subscription(previous)
        self._table.update_item(
            Key={"PK": self._connection_pk(connection.connection_id), "SK": "METADATA"},
            UpdateExpression="SET #document = :document, #expiresAt = :expiresAt",
            ExpressionAttributeNames={"#document": "document", "#expiresAt": "expiresAt"},
            ExpressionAttributeValues={
                ":document": connection.model_dump_json(by_alias=True),
                ":expiresAt": connection.expires_at,
            },
        )
        self._table.put_item(Item=self._subscription_item(connection))

    def delete(self, connection_id: str) -> None:
        connection = self.get(connection_id)
        if connection is not None:
            self._delete_subscription(connection)
        self._table.delete_item(Key={"PK": self._connection_pk(connection_id), "SK": "METADATA"})

    def list_subscribers(self, session_id: SessionId) -> tuple[ConnectionRecord, ...]:
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(self._session_pk(session_id)) & Key("SK").begins_with("CONNECTION#")
            ),
            ConsistentRead=True,
        )
        items = response.get("Items", [])
        if not isinstance(items, list):
            raise RuntimeError("DynamoDB returned invalid connection items")
        return tuple(
            ConnectionRecord.model_validate_json(document)
            for item in items
            if isinstance(item, Mapping) and isinstance((document := item.get("document")), str)
        )

    def _delete_subscription(self, connection: ConnectionRecord) -> None:
        if connection.session_id is None:
            return
        self._table.delete_item(
            Key={
                "PK": self._session_pk(connection.session_id),
                "SK": self._subscription_sk(connection.connection_id),
            }
        )

    @classmethod
    def _connection_item(cls, connection: ConnectionRecord) -> dict[str, object]:
        return {
            "PK": cls._connection_pk(connection.connection_id),
            "SK": "METADATA",
            "entityType": "CONNECTION",
            "expiresAt": connection.expires_at,
            "document": connection.model_dump_json(by_alias=True),
        }

    @classmethod
    def _subscription_item(cls, connection: ConnectionRecord) -> dict[str, object]:
        assert connection.session_id is not None
        return {
            "PK": cls._session_pk(connection.session_id),
            "SK": cls._subscription_sk(connection.connection_id),
            "entityType": "SUBSCRIPTION",
            "expiresAt": connection.expires_at,
            "document": connection.model_dump_json(by_alias=True),
        }

    @staticmethod
    def _connection_pk(connection_id: str) -> str:
        return f"CONNECTION#{connection_id}"

    @staticmethod
    def _session_pk(session_id: str) -> str:
        return f"SESSION#{session_id}"

    @staticmethod
    def _subscription_sk(connection_id: str) -> str:
        return f"CONNECTION#{connection_id}"
