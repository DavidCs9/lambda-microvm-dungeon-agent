"""Small DynamoDB stores for workflow artifacts kept out of Step Functions state."""

from collections.abc import Mapping
from typing import Protocol

from dungeon_agent.control_plane.domain.models import (
    CampaignId,
    OpeningDocument,
    SessionId,
)
from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter, WorldState

AttributeValue = dict[str, str]


class DynamoDbArtifactClient(Protocol):
    def put_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_item(self, **kwargs: object) -> Mapping[str, object]: ...


class DynamoDbAdventurePlans:
    """Session-scoped adventure copies forked from a campaign."""

    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(self, session_id: SessionId, adventure: AdventurePlan) -> str:
        reference = _reference("SESSION", session_id, "ADVENTURE")
        self._put(f"SESSION#{session_id}", "ADVENTURE", adventure.model_dump_json())
        return reference

    def load(self, adventure_ref: str) -> AdventurePlan:
        partition_key, kind = _parse_reference(adventure_ref)
        if kind != "ADVENTURE":
            raise ValueError("reference does not point to an adventure")
        return AdventurePlan.model_validate_json(self._get(partition_key, kind, "document"))

    def _put(self, partition_key: str, kind: str, document: str) -> None:
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "PK": _string(partition_key),
                "SK": _string(f"ARTIFACT#{kind}"),
                "entityType": _string(kind),
                "document": _string(document),
            },
        )

    def _get(self, partition_key: str, kind: str, field: str) -> str:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(partition_key),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return _read_string(response, field)


class DynamoDbCharacterBundles:
    """Session-scoped character and opening copies forked from a campaign."""

    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(
        self,
        session_id: SessionId,
        character: PlayerCharacter,
        opening: OpeningDocument,
    ) -> str:
        kind = "CHARACTER"
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string(f"ARTIFACT#{kind}"),
                "entityType": _string(kind),
                "document": _string(character.model_dump_json()),
                "opening": _string(opening.model_dump_json(by_alias=True)),
            },
        )
        return _reference("SESSION", session_id, kind)

    def load_character(self, character_ref: str) -> PlayerCharacter:
        return PlayerCharacter.model_validate_json(self._get(character_ref, "document"))

    def load_opening(self, character_ref: str) -> OpeningDocument:
        return OpeningDocument.model_validate_json(self._get(character_ref, "opening"))

    def _get(self, reference: str, field: str) -> str:
        partition_key, kind = _parse_reference(reference)
        if kind != "CHARACTER":
            raise ValueError("reference does not point to a character")
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(partition_key),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return _read_string(response, field)


class DynamoDbCampaignAdventurePlans:
    """The immutable adventure generated once per campaign."""

    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(self, campaign_id: CampaignId, adventure: AdventurePlan) -> str:
        reference = _reference("CAMPAIGN", campaign_id, "ADVENTURE")
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "PK": _string(f"CAMPAIGN#{campaign_id}"),
                "SK": _string("ARTIFACT#ADVENTURE"),
                "entityType": _string("ADVENTURE"),
                "document": _string(adventure.model_dump_json()),
            },
        )
        return reference

    def load(self, adventure_ref: str) -> AdventurePlan:
        partition_key, kind = _parse_reference(adventure_ref)
        if kind != "ADVENTURE":
            raise ValueError("reference does not point to an adventure")
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(partition_key),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return AdventurePlan.model_validate_json(_read_string(response, "document"))


class DynamoDbCampaignCharacterBundles:
    """The immutable character and opening generated once per campaign."""

    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(
        self,
        campaign_id: CampaignId,
        character: PlayerCharacter,
        opening: OpeningDocument,
        portrait_key: str | None = None,
    ) -> str:
        kind = "CHARACTER"
        item: dict[str, AttributeValue] = {
            "PK": _string(f"CAMPAIGN#{campaign_id}"),
            "SK": _string(f"ARTIFACT#{kind}"),
            "entityType": _string(kind),
            "document": _string(character.model_dump_json()),
            "opening": _string(opening.model_dump_json(by_alias=True)),
        }
        if portrait_key is not None:
            item["portraitKey"] = _string(portrait_key)
        self._client.put_item(
            TableName=self._table_name,
            Item=item,
        )
        return _reference("CAMPAIGN", campaign_id, kind)

    def load_character(self, character_ref: str) -> PlayerCharacter:
        return PlayerCharacter.model_validate_json(self._get(character_ref, "document"))

    def load_opening(self, character_ref: str) -> OpeningDocument:
        return OpeningDocument.model_validate_json(self._get(character_ref, "opening"))

    def load_portrait_key(self, character_ref: str) -> str | None:
        try:
            return self._get(character_ref, "portraitKey")
        except LookupError, RuntimeError:
            return None

    def _get(self, reference: str, field: str) -> str:
        partition_key, kind = _parse_reference(reference)
        if kind != "CHARACTER":
            raise ValueError("reference does not point to a character")
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(partition_key),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return _read_string(response, field)


class DynamoDbWorldSnapshots:
    """Keep the latest authoritative world snapshot outside workflow state."""

    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(self, session_id: SessionId, world: WorldState) -> None:
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string("ARTIFACT#SNAPSHOT"),
                "entityType": _string("SNAPSHOT"),
                "revision": {"N": str(world.revision)},
                "document": _string(world.model_dump_json()),
            },
        )

    def load(self, session_id: SessionId) -> WorldState:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string("ARTIFACT#SNAPSHOT"),
            },
            ConsistentRead=True,
        )
        return WorldState.model_validate_json(_read_string(response, "document"))


def _reference(aggregate: str, aggregate_id: str, kind: str) -> str:
    return f"dynamodb://{aggregate}#{aggregate_id}/ARTIFACT#{kind}"


def _parse_reference(reference: str) -> tuple[str, str]:
    prefix = "dynamodb://"
    separator = "/ARTIFACT#"
    if not reference.startswith(prefix) or separator not in reference:
        raise ValueError("invalid workflow artifact reference")
    partition_key, kind = reference.removeprefix(prefix).split(separator, maxsplit=1)
    if not partition_key.startswith(("SESSION#", "CAMPAIGN#")):
        raise ValueError("invalid workflow artifact reference")
    return partition_key, kind


def _read_string(response: Mapping[str, object], field: str) -> str:
    item = response.get("Item")
    if not isinstance(item, Mapping):
        raise LookupError("workflow artifact was not found")
    attribute = item.get(field)
    if not isinstance(attribute, Mapping):
        raise RuntimeError(f"workflow artifact is missing {field}")
    value = attribute.get("S")
    if not isinstance(value, str):
        raise RuntimeError(f"workflow artifact {field} is not a string")
    return value


def _string(value: str) -> AttributeValue:
    return {"S": value}
