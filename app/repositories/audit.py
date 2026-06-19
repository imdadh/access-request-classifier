from datetime import datetime
from typing import Optional, Set, Tuple

from sqlalchemy.orm import Session, joinedload

from app.db.models import AccessRequest, Decision, RequestStatus, RequestType

# ── Status transition rules ──────────────────────────────────────────────────
_ALLOWED_TRANSITIONS: Set[Tuple[Optional[RequestStatus], RequestStatus]] = {
    (None, RequestStatus.PENDING_REVIEW),
    (RequestStatus.PENDING_REVIEW, RequestStatus.AUTO_APPROVED),
    (RequestStatus.PENDING_REVIEW, RequestStatus.APPROVED),
    (RequestStatus.PENDING_REVIEW, RequestStatus.REJECTED),
}


def _validate_transition(
    current_status: Optional[RequestStatus],
    new_status: RequestStatus,
) -> None:
    if (current_status, new_status) not in _ALLOWED_TRANSITIONS:
        allowed = [
            f"{cs or 'None'} -> {ns}"
            for cs, ns in sorted(
                _ALLOWED_TRANSITIONS,
                key=lambda p: (p[0].value if p[0] else "", p[1].value),
            )
        ]
        raise ValueError(
            f"Invalid status transition: {current_status!r} -> {new_status!r}. "
            f"Allowed transitions: {allowed}"
        )


def update_request_classification(
    db: Session,
    request_id: int,
    classification: RequestType,
    classification_confidence: float,
    anomaly_score: float,
    recommended_approver: str,
    status: RequestStatus,
    actor: str,
    anomaly_factors: Optional[list[str]] = None,
) -> AccessRequest:
    request = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not request:
        raise ValueError(f"AccessRequest with id {request_id} not found")
    _validate_transition(request.status, status)

    request.classification = classification
    request.classification_confidence = classification_confidence
    request.anomaly_score = anomaly_score
    request.recommended_approver = recommended_approver
    request.status = status
    if anomaly_factors is not None:
        import json

        request.anomaly_factors = json.dumps(anomaly_factors)

    db.commit()
    db.refresh(request)

    record_decision(
        db=db,
        access_request_id=request_id,
        actor=actor,
        action=status.value,
    )

    return request


def record_decision(
    db: Session,
    access_request_id: int,
    actor: str,
    action: str,
    timestamp: Optional[datetime] = None,
) -> Decision:
    try:
        new_status = RequestStatus(action)
    except ValueError as exc:
        raise ValueError(
            f"Invalid action value '{action}'. Must be one of {[s.value for s in RequestStatus]}"
        ) from exc

    request = (
        db.query(AccessRequest).filter(AccessRequest.id == access_request_id).first()
    )
    if not request:
        raise ValueError(f"AccessRequest with id {access_request_id} not found")

    _validate_transition(request.status, new_status)

    if timestamp is None:
        timestamp = datetime.utcnow()

    decision = Decision(
        access_request_id=access_request_id,
        actor=actor,
        action=action,
        timestamp=timestamp,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def get_request_lifecycle(db: Session, request_id: int) -> Optional[dict]:
    """
    Retrieve the full lifecycle of a single access request for audit purposes.

    Returns a dictionary containing the request record (all fields) and an ordered
    list of decision entries (oldest first). Returns None if the request does not
    exist.
    """
    request = (
        db.query(AccessRequest)
        .options(joinedload(AccessRequest.decisions))
        .filter(AccessRequest.id == request_id)
        .one_or_none()
    )
    if not request:
        return None

    # Order decisions by timestamp (ascending)
    decisions = sorted(request.decisions, key=lambda d: d.timestamp)

    return {
        "request": request,
        "decisions": decisions,
    }
