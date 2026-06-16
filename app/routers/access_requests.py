from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.schemas import AccessRequestCreate, AccessRequestResponse
from app.db.models import RequestType, RequestStatus, AccessRequest
from app.db.session import get_db

router = APIRouter()


@router.post("/access-requests", response_model=AccessRequestResponse, status_code=201)
async def create_access_request(request: AccessRequestCreate) -> AccessRequestResponse:
    """Accept and validate a free-text access request.

    This endpoint currently returns a placeholder response. The full
    classification, role mapping, anomaly scoring, and approver
    recommendation pipeline will be integrated in subsequent sub-tasks.

    Input validation is handled automatically by FastAPI via the
    `AccessRequestCreate` schema (both `requester_id` and `request_text`
    must be non-empty strings). Malformed requests receive a 422 error
    with a descriptive message.
    """
    # Placeholder response — real logic will be added later.
    return AccessRequestResponse(
        id=0,  # Placeholder; actual ID assigned after database insert
        requester_id=request.requester_id,
        request_text=request.request_text,
        classification=RequestType.DATA_ACCESS,  # Dummy value
        classification_confidence=0.0,
        role_mappings=[],
        anomaly_score=0.0,
        anomaly_factors=None,
        recommended_approver=None,
        status=RequestStatus.PENDING_REVIEW,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@router.get("/access-requests/{request_id}", response_model=AccessRequestResponse)
async def get_access_request(
    request_id: int,
    db: Session = Depends(get_db),
) -> AccessRequestResponse:
    """Retrieve a submitted access request by its database ID.

    Returns the full structured response including current status so that
    requesters can track their request lifecycle.
    """
    record = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Access request not found")

    return AccessRequestResponse(
        id=record.id,
        requester_id=record.requester_id,
        request_text=record.request_text,
        classification=record.classification,
        classification_confidence=record.classification_confidence,
        role_mappings=[],  # Placeholder; will be populated from stored mapping in later tasks
        anomaly_score=record.anomaly_score,
        anomaly_factors=[record.anomaly_factors] if record.anomaly_factors else None,
        recommended_approver=record.recommended_approver,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
