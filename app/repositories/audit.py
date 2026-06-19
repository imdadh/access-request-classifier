from sqlalchemy.orm import Session

from app.db.models import AccessRequest, RequestStatus, RequestType


def update_request_classification(
    db: Session,
    request_id: int,
    classification: RequestType,
    classification_confidence: float,
    anomaly_score: float,
    recommended_approver: str,
    status: RequestStatus,
) -> AccessRequest:
    """Persist the classification result, anomaly score, recommended approver, and
    routing decision to the AccessRequest record identified by ``request_id``.

    Args:
        db: Active database session.
        request_id: The primary key of the AccessRequest to update.
        classification: The classified request type.
        classification_confidence: Confidence in the classification (0.0–1.0).
        anomaly_score: Computed anomaly score (0.0–1.0, higher = more anomalous).
        recommended_approver: Email or queue identifier of the recommended approver.
        status: The routing decision (auto_approved or pending_review).

    Returns:
        The updated AccessRequest ORM instance (already refreshed from the DB).

    Raises:
        ValueError: If no AccessRequest with the given id exists.
    """
    request = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not request:
        raise ValueError(f"AccessRequest with id {request_id} not found")

    request.classification = classification
    request.classification_confidence = classification_confidence
    request.anomaly_score = anomaly_score
    request.recommended_approver = recommended_approver
    request.status = status

    db.commit()
    db.refresh(request)
    return request
