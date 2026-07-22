from collections.abc import Mapping

from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignRecord,
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
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
)


class DynamoDbCampaignRepository(DynamoDbAggregateRepository):
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
            aggregate="CAMPAIGN",
            aggregate_id_attr="campaignId",
            already_exists_error=CampaignAlreadyExistsError,
            revision_conflict_error=CampaignRevisionConflictError,
            sequence_conflict_error=CampaignEventSequenceConflictError,
            record_id=lambda campaign: campaign.campaign_id,
            event_record_id=lambda event: event.campaign_id,
            decode_record=self._campaign_from_item,
            decode_event=CampaignEvent.model_validate_json,
            idempotency_ttl_seconds=idempotency_ttl_seconds,
        )

    def count_by_owner(self, owner_id: str) -> int:
        return self._table.count_index_items(
            index_name="ByOwner",
            key_condition="ownerId = :owner",
            values={":owner": string(owner_id)},
        )

    def list_by_owner(
        self, owner_id: str, *, status: str | None = None
    ) -> tuple[CampaignRecord, ...]:
        values: dict[str, AttributeValue] = {":owner": string(owner_id)}
        filter_expression = None
        names = None
        if status is not None:
            values[":status"] = string(status)
            filter_expression = "#status = :status"
            names = {"#status": "status"}
        campaigns = [
            self._campaign_from_item(item)
            for item in self._table.list_index_items(
                index_name="ByOwner",
                key_condition="ownerId = :owner",
                values=values,
                filter_expression=filter_expression,
                names=names,
            )
        ]
        campaigns.sort(key=lambda campaign: campaign.created_at, reverse=True)
        return tuple(campaigns[:50])

    @staticmethod
    def _campaign_from_item(item: Mapping[str, object]) -> CampaignRecord:
        campaign = CampaignRecord.model_validate_json(attribute_string(item, "document"))
        return campaign.model_copy(
            update={
                "revision": attribute_int(item, "revision"),
                "last_event_sequence": attribute_int(item, "lastEventSequence"),
            }
        )


def create_dynamodb_campaign_repository(
    table_name: str,
    *,
    region_name: str | None = None,
    idempotency_ttl_seconds: int = 86_400,
) -> DynamoDbCampaignRepository:
    client = create_dynamodb_client(region_name)
    return DynamoDbCampaignRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
