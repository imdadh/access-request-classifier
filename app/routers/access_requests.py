import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AccessRequest, RequestStatus, RequestType
from app.db.session import get_db
from app.llm.classifier import classify as classify_request
from app.llm.default_provider import DefaultLLMProvider
from app.llm.protocol import ClassificationError
from app.schemas import AccessRequestCreate, AccessRequestResponse
from app.services.role_mapping import map_roles
from app.services.anomaly import compute_anomaly_score
from app.services.approver import resolve_approver
from app.services.routing import route_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/access-requests", tags=["access-requests"])


@router.post("/", response_model=AccessRequestResponse, status_code=201)
def create_access_request(
    body: AccessRequestCreate,
    db: Session = Depends(get_db),
):
    """
    Accept a free-text access request, classify, map roles, score anomaly,
    recommend approver, and route (auto-approve or manual review).
    """
    # 1. Validate requester exists (seed data provides some users)
    #    (Skipped for simplicity – rely on the foreign key constraint in the model)

    # 2. Run classification
    provider = DefaultLLMProvider.create_default()
    try:
        classification = classify_request(provider, body.request_text)
    except ClassificationError as exc:
        logger.warning(
            "Classification failed for request from %s: %s",
            body.requester_id,
            exc,
        )
        # Classification failure – route directly to manual review.
        # Use a sentinel classification so the database record is still valid.
        # (The model requires a non-null RequestType; we use DATA_ACCESS as a
        # fallback but the low confidence and anomaly score will cause manual review.)
        classification = None

    # 3. Create the AccessRequest record in the database
    new_request = AccessRequest(
        requester_id=body.requester_id,
        request_text=body.request_text,
        classification=(
            classification.request_type if classification else RequestType.DATA_ACCESS
        ),
        classification_confidence=(
            classification.confidence if classification else 0.0
        ),
        status=RequestStatus.PENDING_REVIEW,  # will be overridden by routing
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    # 4. If classification succeeded, run role mapping, anomaly scoring, approver, routing
    if classification:
        role_mappings = map_roles(
            db=db,
            request_text=body.request_text,
            request_type=classification.request_type,
        )
        anomaly_score, anomaly_factors = compute_anomaly_score(
            db=db,
            requester_id=body.requester_id,
            request_type=classification.request_type,
            resource=None,  # could be extracted from role_mappings later
            role=None,
            request_id=new_request.id,  # persists factors as JSON
        )
        recommended_approver = resolve_approver(role_mappings)
        decision = route_request(
            anomaly_score=anomaly_score,
            role_mappings=role_mappings,
        )
    else:
        # Classification failed – use empty role mappings, high anomaly, default approver
        role_mappings = []
        anomaly_score = 1.0
        anomaly_factors = ["Classification failed or was too ambiguous."]
        recommended_approver = settings.default_reviewer_queue
        decision = "pending_review"

    # 5. Update the AccessRequest record with the final values
    new_request.anomaly_score = anomaly_score
    new_request.recommended_approver = recommended_approver
    new_request.status = RequestStatus(decision)
    new_request.anomaly_factors = (
        json.dumps(anomaly_factors) if anomaly_factors else None
    )
    db.commit()
    db.refresh(new_request)

    # 6. Build response – decode anomaly_factors from JSON back to list
    response_anomaly_factors: Optional[list[str]] = None
    if new_request.anomaly_factors:
        try:
            response_anomaly_factors = json.loads(new_request.anomaly_factors)
        except (json.JSONDecodeError, TypeError):
            response_anomaly_factors = [str(new_request.anomaly_factors)]

    return AccessRequestResponse(
        id=new_request.id,
        requester_id=new_request.requester_id,
        request_text=new_request.request_text,
        classification=new_request.classification,
        classification_confidence=new_request.classification_confidence,
        role_mappings=role_mappings,
        anomaly_score=new_request.anomaly_score,
        anomaly_factors=response_anomaly_factors,
        recommended_approver=new_request.recommended_approver,
        status=new_request.status,
        created_at=new_request.created_at,
        updated_at=new_request.updated_at,
    )


@router.get("/{request_id}", response_model=AccessRequestResponse)
def get_request_status(
    request_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve the current status and full details of an access request."""
    request = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Decode anomaly_factors
    response_anomaly_factors: Optional[list[str]] = None
    if request.anomaly_factors:
        try:
            response_anomaly_factors = json.loads(request.anomaly_factors)
        except (json.JSONDecodeError, TypeError):
            response_anomaly_factors = [str(request.anomaly_factors)]

    return AccessRequestResponse(
        id=request.id,
        requester_id=request.requester_id,
        request_text=request.request_text,
        classification=request.classification,
        classification_confidence=request.classification_confidence,
        role_mappings=[],  # not persisted yet (see parent 5.0); empty on status lookup
        anomaly_score=request.anomaly_score,
        anomaly_factors=response_anomaly_factors,
        recommended_approver=request.recommended_approver,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )
