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
from app.repositories.audit import (
    update_request_classification,
    record_decision,
    get_request_lifecycle,
)
from app.schemas import (
    AccessRequestCreate,
    AccessRequestResponse,
    AccessRequestAuditResponse,
    DecisionResponse,
)
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
    provider = DefaultLLMProvider.create_default()
    try:
        classification = classify_request(provider, body.request_text)
    except ClassificationError as exc:
        logger.warning(
            "Classification failed for request from %s: %s",
            body.requester_id,
            exc,
        )
        classification = None

    new_request = AccessRequest(
        requester_id=body.requester_id,
        request_text=body.request_text,
        classification=(
            classification.request_type if classification else RequestType.DATA_ACCESS
        ),
        classification_confidence=(
            classification.confidence if classification else 0.0
        ),
        status=None,
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    # Genesis transition: None -> PENDING_REVIEW (applied + logged here).
    record_decision(
        db=db,
        access_request_id=new_request.id,
        actor="system",
        action=RequestStatus.PENDING_REVIEW.value,
    )

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
            resource=None,
            role=None,
            request_id=new_request.id,
        )
        recommended_approver = resolve_approver(role_mappings)
        decision = route_request(
            anomaly_score=anomaly_score,
            role_mappings=role_mappings,
        )
    else:
        role_mappings = []
        anomaly_score = 1.0
        anomaly_factors = ["Classification failed or was too ambiguous."]
        recommended_approver = settings.default_reviewer_queue
        decision = "pending_review"

    updated_request = update_request_classification(
        db=db,
        request_id=new_request.id,
        classification=(
            classification.request_type if classification else RequestType.DATA_ACCESS
        ),
        classification_confidence=(
            classification.confidence if classification else 0.0
        ),
        anomaly_score=anomaly_score,
        recommended_approver=recommended_approver,
        status=RequestStatus(decision),
        actor="system",
        anomaly_factors=anomaly_factors,
    )

    response_anomaly_factors: Optional[list[str]] = None
    if updated_request.anomaly_factors:
        try:
            response_anomaly_factors = json.loads(updated_request.anomaly_factors)
        except (json.JSONDecodeError, TypeError):
            response_anomaly_factors = [str(updated_request.anomaly_factors)]

    return AccessRequestResponse(
        id=updated_request.id,
        requester_id=updated_request.requester_id,
        request_text=updated_request.request_text,
        classification=updated_request.classification,
        classification_confidence=updated_request.classification_confidence,
        role_mappings=role_mappings,
        anomaly_score=updated_request.anomaly_score,
        anomaly_factors=response_anomaly_factors,
        recommended_approver=updated_request.recommended_approver,
        status=updated_request.status,
        created_at=updated_request.created_at,
        updated_at=updated_request.updated_at,
    )


@router.get("/{request_id}", response_model=AccessRequestResponse)
def get_request_status(
    request_id: int,
    db: Session = Depends(get_db),
):
    request = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

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
        role_mappings=[],
        anomaly_score=request.anomaly_score,
        anomaly_factors=response_anomaly_factors,
        recommended_approver=request.recommended_approver,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


@router.get("/{request_id}/audit", response_model=AccessRequestAuditResponse)
def get_request_audit(
    request_id: int,
    db: Session = Depends(get_db),
):
    """
    Retrieve the full audit lifecycle of an access request, including its current
    state and all historical decisions (state transitions).
    """
    lifecycle = get_request_lifecycle(db, request_id)
    if lifecycle is None:
        raise HTTPException(status_code=404, detail="Request not found")

    request = lifecycle["request"]
    decisions = lifecycle["decisions"]

    # Convert request to AccessRequestResponse schema
    response_anomaly_factors: Optional[list[str]] = None
    if request.anomaly_factors:
        try:
            response_anomaly_factors = json.loads(request.anomaly_factors)
        except (json.JSONDecodeError, TypeError):
            response_anomaly_factors = [str(request.anomaly_factors)]

    request_response = AccessRequestResponse(
        id=request.id,
        requester_id=request.requester_id,
        request_text=request.request_text,
        classification=request.classification,
        classification_confidence=request.classification_confidence,
        role_mappings=[],  # not persisted; empty for audit view
        anomaly_score=request.anomaly_score,
        anomaly_factors=response_anomaly_factors,
        recommended_approver=request.recommended_approver,
        status=request.status,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )

    decision_responses = [
        DecisionResponse(
            id=d.id,
            access_request_id=d.access_request_id,
            actor=d.actor,
            action=d.action,
            timestamp=d.timestamp,
        )
        for d in decisions
    ]

    return AccessRequestAuditResponse(
        request=request_response,
        decisions=decision_responses,
    )
