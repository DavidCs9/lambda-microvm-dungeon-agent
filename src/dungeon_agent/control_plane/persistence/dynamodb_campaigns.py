"""DynamoDB single-table adapter for campaigns and their ordered events."""

from collections.abc import Mapping

from dungeon_agent.control_plane.domain.models import (
    CampaignEvent,
    CampaignId,
    CampaignRecord,
)
from dungeon_agent.control_plane.persistence.dynamo_helpers import (
    AttributeValue,
    DynamoDbAggregateStore,
    attribute_int,
    attribute_string,
    create_dynamodb_client,
    event_item,
    metadata_item,
    string,
)
from dungeon_agent.control_plane.persistence.dynamo_types import DynamoDbClient
from dungeon_agent.control_plane.persistence.errors import (
    CampaignAlreadyExistsError,
    CampaignEventSequenceConflictError,
    CampaignRevisionConflictError,
)


class DynamoDbCampaignRepository:
    """Implement campaign and campaign-event ports with a single-table layout."""

    def __init__(
        self,
        client: DynamoDbClient,
        table_name: str,
        *,
        idempotency_ttl_seconds: int = 86_400,
    ) -> None:
        if idempotency_ttl_seconds <= 0:
            raise ValueError("idempotency_ttl_seconds must be positive")
        self._table = DynamoDbAggregateStore(client, table_name, "CAMPAIGN")
        self._idempotency_ttl_seconds = idempotency_ttl_seconds

    def create(self, campaign: CampaignRecord, idempotency_key: str) -> CampaignRecord:
        """Atomically persist a campaign and its owner-scoped idempotency record."""
        existing = self.find_by_idempotency_key(campaign.owner_id, idempotency_key)
        if existing is not None:
            return existing

        try:
            self._table.create_with_idempotency(
                aggregate_item=self._campaign_item(campaign),
                owner_id=campaign.owner_id,
                idempotency_key=idempotency_key,
                aggregate_id_attr="campaignId",
                aggregate_id=campaign.campaign_id,
                created_at=campaign.created_at,
                ttl_seconds=self._idempotency_ttl_seconds,
            )
        except self._table.transaction_cancelled as error:
            existing = self.find_by_idempotency_key(campaign.owner_id, idempotency_key)
            if existing is not None:
                return existing
            raise CampaignAlreadyExistsError(
                f"campaign or idempotency record already exists: {campaign.campaign_id}"
            ) from error
        return campaign

    def get(self, campaign_id: CampaignId) -> CampaignRecord | None:
        """Read a campaign consistently so revision checks see recent writes."""
        raw_item = self._table.get_metadata_item(campaign_id)
        if raw_item is None:
            return None
        return self._campaign_from_item(raw_item)

    def find_by_idempotency_key(self, owner_id: str, idempotency_key: str) -> CampaignRecord | None:
        """Resolve an owner-scoped idempotency key to its original campaign."""
        campaign_id = self._table.get_idempotency_id(owner_id, idempotency_key, "campaignId")
        if campaign_id is None:
            return None
        return self.get(campaign_id)

    def save(self, campaign: CampaignRecord, *, expected_revision: int) -> CampaignRecord:
        """Save one state revision without overwriting the independent event counter."""
        if campaign.revision != expected_revision + 1:
            raise CampaignRevisionConflictError(
                "saved campaign revision must be exactly one greater than expected revision"
            )
        try:
            attributes = self._table.save_metadata(
                aggregate_id=campaign.campaign_id,
                document=campaign.model_dump_json(by_alias=True),
                revision=campaign.revision,
                expected_revision=expected_revision,
                updated_at=campaign.updated_at,
                status=campaign.status.value,
            )
        except self._table.conditional_check_failed as error:
            raise CampaignRevisionConflictError(
                f"campaign revision conflict: {campaign.campaign_id}"
            ) from error
        return self._campaign_from_item(attributes)

    def append(self, event: CampaignEvent, *, expected_previous_sequence: int) -> None:
        """Atomically advance the campaign counter and store exactly one event."""
        if event.sequence != expected_previous_sequence + 1:
            raise CampaignEventSequenceConflictError(
                "event sequence must be exactly one greater than expected previous sequence"
            )
        try:
            self._table.append_event(
                aggregate_id=event.campaign_id,
                event_item=event_item(
                    aggregate="CAMPAIGN",
                    aggregate_id=event.campaign_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    document=event.model_dump_json(by_alias=True),
                ),
                sequence=event.sequence,
                expected_previous_sequence=expected_previous_sequence,
            )
        except self._table.transaction_cancelled as error:
            raise CampaignEventSequenceConflictError(
                f"event sequence conflict: {event.campaign_id}/{event.sequence}"
            ) from error

    def list_after(self, campaign_id: CampaignId, sequence: int) -> tuple[CampaignEvent, ...]:
        """Query all events after a sequence in ascending order."""
        return self._table.list_events_after(
            campaign_id,
            sequence,
            CampaignEvent.model_validate_json,
        )

    def count_by_owner(self, owner_id: str) -> int:
        """Count every campaign one owner has created through the ``ByOwner`` index."""
        return self._table.count_index_items(
            index_name="ByOwner",
            key_condition="ownerId = :owner",
            values={":owner": string(owner_id)},
        )

    def list_by_owner(
        self, owner_id: str, *, status: str | None = None
    ) -> tuple[CampaignRecord, ...]:
        """List one owner's campaigns via ``ByOwner``, newest ``createdAt`` first."""
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

    @classmethod
    def _campaign_item(cls, campaign: CampaignRecord) -> dict[str, AttributeValue]:
        return metadata_item(
            aggregate="CAMPAIGN",
            aggregate_id=campaign.campaign_id,
            aggregate_id_attr="campaignId",
            owner_id=campaign.owner_id,
            status=campaign.status.value,
            revision=campaign.revision,
            last_event_sequence=campaign.last_event_sequence,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
            document=campaign.model_dump_json(by_alias=True),
        )

    @classmethod
    def _campaign_from_item(cls, item: Mapping[str, object]) -> CampaignRecord:
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
    """Create one reusable DynamoDB client and its campaign repository adapter."""
    client = create_dynamodb_client(region_name)
    return DynamoDbCampaignRepository(
        client,
        table_name,
        idempotency_ttl_seconds=idempotency_ttl_seconds,
    )
