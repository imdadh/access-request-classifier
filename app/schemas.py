from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.models import RequestType, RequestStatus


class AccessRequestCreate(BaseModel):
    requester_id: str = Field(
        ..., min_length=1, description="The unique identifier of the requester."
    )
    request_text: str = Field(
        ..., min_length=1, description="Free-text description of the access request."
    )


class RoleMapping(BaseModel):
    role_name: str = Field(
        ..., description="Name of the role in the synthetic catalog."
    )
    resource: str = Field(
        ..., description="The resource that this role grants access to."
    )
    owner: str = Field(..., description="Email or identifier of the resource owner.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score for this role mapping."
    )


class AccessRequestResponse(BaseModel):
    id: int = Field(..., description="Database ID of the access request.")
    requester_id: str = Field(..., description="ID of the requester.")
    request_text: str = Field(..., description="Original free-text request.")
    classification: RequestType = Field(..., description="Classified request type.")
    classification_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the classification."
    )
    role_mappings: list[RoleMapping] = Field(
        default_factory=list,
        description="Suggested roles from the catalog that satisfy the request.",
    )
    anomaly_score: float = Field(
        ..., ge=0.0, le=1.0, description="Anomaly score relative to requester history."
    )
    anomaly_factors: Optional[list[str]] = Field(
        None, description="Human-readable factors contributing to the anomaly score."
    )
    recommended_approver: Optional[str] = Field(
        None, description="Recommended approver for this request."
    )
    status: RequestStatus = Field(
        ...,
        description="Current status of the request (pending_review, auto_approved, etc.).",
    )
    created_at: datetime = Field(
        ..., description="Timestamp when the request was created."
    )
    updated_at: datetime = Field(..., description="Timestamp of the last update.")


class DecisionResponse(BaseModel):
    """A single state-transition record for the audit trail."""

    id: int = Field(..., description="Database ID of the decision.")
    access_request_id: int = Field(..., description="ID of the access request.")
    actor: str = Field(
        ..., description="Identifier of the actor (system or named reviewer)."
    )
    action: str = Field(
        ..., description="The action taken (e.g., 'pending_review', 'auto_approved')."
    )
    timestamp: datetime = Field(..., description="Timestamp of the decision.")


class AccessRequestAuditResponse(BaseModel):
    """Full lifecycle details of an access request, including all decisions."""

    request: AccessRequestResponse = Field(
        ..., description="The current state of the request."
    )
    decisions: list[DecisionResponse] = Field(
        ...,
        description="Ordered list of all decisions (state transitions) for this request.",
    )
