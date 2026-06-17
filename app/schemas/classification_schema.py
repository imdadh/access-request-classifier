from pydantic import BaseModel, Field, model_validator

from app.db.models import RequestType


class ClassificationResult(BaseModel):
    """Structured output schema for the LLM classification response.

    This schema defines the exact shape of the classification dictionary the
    LLM must return. Any output that fails validation (wrong keys, invalid
    enum, out-of-range confidence) is treated as a classification failure
    and routed to manual review.

    Attributes:
        request_type: One of the four defined request types.
        confidence: A float in [0.0, 1.0] indicating the model's confidence
            in the classification.
    """

    request_type: RequestType = Field(
        ...,
        description="The classified request type.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification.",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def strip_extra_keys(cls, values: dict) -> dict:
        """Ensure only allowed keys are present; extra keys cause failure."""
        allowed = {"request_type", "confidence"}
        extra = set(values.keys()) - allowed
        if extra:
            raise ValueError(f"Unexpected keys: {extra}")
        return values
