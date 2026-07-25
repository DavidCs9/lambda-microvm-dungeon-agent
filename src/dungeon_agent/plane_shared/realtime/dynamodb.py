from collections.abc import Mapping
from typing import Any

from dungeon_agent.plane_shared.domain.models import CampaignId, SessionId
from dungeon_agent.plane_shared.realtime.models import ConnectionRecord


class DynamoDbConnectionRepository:
    def __init__(self, table: Any) -> None:
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
        target_pk = self._subscription_pk(connection)
        if target_pk is None:
            raise ValueError("a subscription requires a session_id or campaign_id")
        previous = self.get(connection.connection_id)
        if previous is not None:
            previous_pk = self._subscription_pk(previous)
            if previous_pk is not None and previous_pk != target_pk:
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
        self._table.put_item(Item=self._subscription_item(connection, target_pk))

    def delete(self, connection_id: str) -> None:
        connection = self.get(connection_id)
        if connection is not None:
            self._delete_subscription(connection)
        self._table.delete_item(Key={"PK": self._connection_pk(connection_id), "SK": "METADATA"})

    def list_subscribers(self, session_id: SessionId) -> tuple[ConnectionRecord, ...]:
        return self._subscribers_of(self._session_pk(session_id))

    def list_campaign_subscribers(self, campaign_id: CampaignId) -> tuple[ConnectionRecord, ...]:
        return self._subscribers_of(self._campaign_pk(campaign_id))

    def _subscribers_of(self, aggregate_pk: str) -> tuple[ConnectionRecord, ...]:
        response = self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :connectionPrefix)",
            ExpressionAttributeValues={
                ":pk": aggregate_pk,
                ":connectionPrefix": "CONNECTION#",
            },
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
        target_pk = self._subscription_pk(connection)
        if target_pk is None:
            return
        self._table.delete_item(
            Key={
                "PK": target_pk,
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
    def _subscription_item(cls, connection: ConnectionRecord, target_pk: str) -> dict[str, object]:
        return {
            "PK": target_pk,
            "SK": cls._subscription_sk(connection.connection_id),
            "entityType": "SUBSCRIPTION",
            "expiresAt": connection.expires_at,
            "document": connection.model_dump_json(by_alias=True),
        }

    @classmethod
    def _subscription_pk(cls, connection: ConnectionRecord) -> str | None:
        if connection.session_id is not None:
            return cls._session_pk(connection.session_id)
        if connection.campaign_id is not None:
            return cls._campaign_pk(connection.campaign_id)
        return None

    @staticmethod
    def _connection_pk(connection_id: str) -> str:
        return f"CONNECTION#{connection_id}"

    @staticmethod
    def _session_pk(session_id: str) -> str:
        return f"SESSION#{session_id}"

    @staticmethod
    def _campaign_pk(campaign_id: str) -> str:
        return f"CAMPAIGN#{campaign_id}"

    @staticmethod
    def _subscription_sk(connection_id: str) -> str:
        return f"CONNECTION#{connection_id}"
