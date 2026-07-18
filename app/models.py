from pydantic import BaseModel, ConfigDict, Field


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=500)


class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    location: str
    inventory: list[str]
    story: list[str]


class HealthResponse(BaseModel):
    status: str
