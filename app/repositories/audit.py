from datetime import datetime
from typing import Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.db.models import AccessRequest, Decision, RequestStatus, RequestType

# ── Status transition rules ──────────────────────────────────────────────────
# Define the set of valid (from_status, to_status) pairs.
# For initial request creation we use None as the ‘from’ status.
_ALLOWED_TRANSITIONS: Set[Tuple[Optional[RequestStatus], RequestStatus]] = {
    (None, RequestStatus.PENDING_REVIEW),  # initial creation
    (RequestStatus.PENDING_REVIEW, RequestStatus.AUTO_APPROVED),
    (RequestStatus.PENDING_REVIEW, RequestStatus.APPROVED),
    (RequestStatus.PENDING_REVIEW, RequestStatus.REJECTED),
}


def _validate_transition(
    current_status: Optional[RequestStatus],
    new_status: RequestStatus,
) -> None:
    """Raise ValueError if the transition is not allowed."""
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
    """Persist the classification result, anomaly score, recommended approver, and
    routing decision to the AccessRequest record identified by ``request_id``.
    Also records a decision entry for the state transition.

    Args:
        db: Active database session.
        request_id: The primary key of the AccessRequest to update.
        classification: The classified request type.
        classification_confidence: Confidence in the classification (0.0–1.0).
        anomaly_score: Computed anomaly score (0.0–1.0, higher = more anomalous).
        recommended_approver: Email or queue identifier of the recommended approver.
        status: The routing decision (auto_approved or pending_review).
        actor: Identifier of the actor performing this transition (e.g., "system" or a reviewer email).
        anomaly_factors: Optional human-readable list of factors explaining the anomaly score.
            If provided, stored as JSON in the request record.

    Returns:
        The updated AccessRequest ORM instance (already refreshed from the DB).

    Raises:
        ValueError: If no AccessRequest with the given id exists.
        ValueError: If the requested status transition is not allowed.
    """
    request = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not request:
        raise ValueError(f"AccessRequest with id {request_id} not found")

    # Validate the status transition from current status to the new status.
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
    """Record a state transition (decision) in the decisions table.

    Validates that the new status (derived from ``action``) is a legal transition
    from the current status of the access request.

    Args:
        db: Active database session.
        access_request_id: The ID of the access request this decision applies to.
        actor: Identifier of the actor (e.g., "system", reviewer email).
        action: The new status value after the transition (e.g., "pending_review", "auto_approved").
        timestamp: Explicit timestamp; if None, uses current UTC time.

    Returns:
        The newly created Decision ORM instance.

    Raises:
        ValueError: If the access request does not exist.
        ValueError: If the status value in ``action`` is not a valid RequestStatus.
        ValueError: If the transition is not allowed.
    """
    # Convert the action string to a RequestStatus enum member.
    try:
        new_status = RequestStatus(action)
    except ValueError as exc:
        raise ValueError(
            f"Invalid action value '{action}'. Must be one of {[s.value for s in RequestStatus]}"
        ) from exc

    # Fetch the request to know its current status.
    request = (
        db.query(AccessRequest).filter(AccessRequest.id == access_request_id).first()
    )
    if not request:
        raise ValueError(f"AccessRequest with id {access_request_id} not found")

    # Validate the transition from current status to new status.
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
