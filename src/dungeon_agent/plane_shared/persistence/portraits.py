from typing import Any

from dungeon_agent.plane_shared.domain.models import CampaignId

PORTRAIT_CONTENT_TYPE = "image/png"


def portrait_object_key(campaign_id: CampaignId) -> str:
    return f"portraits/{campaign_id}.png"


class S3PortraitStore:
    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        *,
        expires_in_seconds: int = 3_600,
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._expires_in_seconds = expires_in_seconds

    def save(self, campaign_id: CampaignId, image: bytes) -> str:
        key = portrait_object_key(campaign_id)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=image,
            ContentType=PORTRAIT_CONTENT_TYPE,
        )
        return key

    def presigned_url(self, key: str) -> str:
        return str(
            self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._expires_in_seconds,
            )
        )
