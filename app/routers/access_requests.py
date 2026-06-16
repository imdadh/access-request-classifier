from datetime import datetime

from fastapi import APIRouter

from app.schemas import AccessRequestCreate, AccessRequestResponse
from app.db.models import RequestType, RequestStatus

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
