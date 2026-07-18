"""Small DynamoDB stores for workflow artifacts kept out of Step Functions state."""

from collections.abc import Mapping
from typing import Protocol

from dungeon_agent.control_plane.domain.models import OpeningDocument, SessionId
from dungeon_agent.domain.game import AdventurePlan, PlayerCharacter

AttributeValue = dict[str, str]


class DynamoDbArtifactClient(Protocol):
    def put_item(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_item(self, **kwargs: object) -> Mapping[str, object]: ...


class DynamoDbAdventurePlans:
    def __init__(self, client: DynamoDbArtifactClient, table_name: str) -> None:
        self._client = client
        self._table_name = table_name

    def save(self, session_id: SessionId, adventure: AdventurePlan) -> str:
        reference = _reference(session_id, "ADVENTURE")
        self._put(session_id, "ADVENTURE", adventure.model_dump_json())
        return reference

    def load(self, adventure_ref: str) -> AdventurePlan:
        session_id, kind = _parse_reference(adventure_ref)
        if kind != "ADVENTURE":
            raise ValueError("reference does not point to an adventure")
        return AdventurePlan.model_validate_json(self._get(session_id, kind, "document"))

    def _put(self, session_id: SessionId, kind: str, document: str) -> None:
        self._client.put_item(
            TableName=self._table_name,
            Item={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string(f"ARTIFACT#{kind}"),
                "entityType": _string(kind),
                "document": _string(document),
            },
        )

    def _get(self, session_id: SessionId, kind: str, field: str) -> str:
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return _read_string(response, field)


class DynamoDbCharacterBundles:
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
        return _reference(session_id, kind)

    def load_character(self, character_ref: str) -> PlayerCharacter:
        return PlayerCharacter.model_validate_json(self._get(character_ref, "document"))

    def load_opening(self, character_ref: str) -> OpeningDocument:
        return OpeningDocument.model_validate_json(self._get(character_ref, "opening"))

    def _get(self, reference: str, field: str) -> str:
        session_id, kind = _parse_reference(reference)
        if kind != "CHARACTER":
            raise ValueError("reference does not point to a character")
        response = self._client.get_item(
            TableName=self._table_name,
            Key={
                "PK": _string(f"SESSION#{session_id}"),
                "SK": _string(f"ARTIFACT#{kind}"),
            },
            ConsistentRead=True,
        )
        return _read_string(response, field)


def _reference(session_id: SessionId, kind: str) -> str:
    return f"dynamodb://SESSION#{session_id}/ARTIFACT#{kind}"


def _parse_reference(reference: str) -> tuple[SessionId, str]:
    prefix = "dynamodb://SESSION#"
    separator = "/ARTIFACT#"
    if not reference.startswith(prefix) or separator not in reference:
        raise ValueError("invalid workflow artifact reference")
    raw_session_id, kind = reference.removeprefix(prefix).split(separator, maxsplit=1)
    return raw_session_id, kind


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
