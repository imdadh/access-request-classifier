from pydantic import BaseModel, Field


class AccessRequestCreate(BaseModel):
    """Schema for the incoming access request. Both fields are required and must be non-empty."""

    requester_id: str = Field(
        ..., min_length=1, description="The unique identifier of the requester."
    )
    request_text: str = Field(
        ..., min_length=1, description="Free-text description of the access request."
    )
