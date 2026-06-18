import logging
from typing import List, Tuple, Optional

from sqlalchemy.orm import Session

from app.db.models import RequestType, RequestStatus, AccessRequest

logger = logging.getLogger(__name__)

# Minimum number of prior accepted requests before we consider a requester "warm"
MIN_HISTORY_FOR_WARM_START = 2

# Default anomaly score for cold-start requesters
COLD_START_ANOMALY_SCORE = 0.8


def compute_anomaly_score(
    db: Session,
    requester_id: str,
    request_type: RequestType,
    resource: Optional[str] = None,
    role: Optional[str] = None,
) -> Tuple[float, List[str]]:
    """Compute a 0.0–1.0 anomaly score for the given request by comparing it to
    the requester's prior accepted requests (auto_approved or approved status).

    The score reflects how unusual the request is relative to the requester's
    historical pattern. A higher score means the request is more anomalous.

    The implementation uses a simple heuristic:
    - If the requester has fewer than `MIN_HISTORY_FOR_WARM_START` prior accepted
      requests, return a high anomaly score (cold-start).
    - Otherwise, compute the fraction of prior accepted requests that share the
      same request_type. A lower fraction yields a higher anomaly score.
    - Additionally, if a resource is provided, compute the fraction of prior
      requests that targeted the same resource (by matching against the resource
      stored in the request_text or the role catalog; for now we check against
      the resource stored in the AccessRequest's anomaly_factors or a dedicated
      field? We don't have a resource field on AccessRequest, so we rely on
      request_type only for this initial heuristic. The method is designed to be
      extensible when more data becomes available.

    Args:
        db: Active database session.
        requester_id: The unique identifier of the requester.
        request_type: The classified request type of the current request.
        resource: Optional resource identifier (e.g., dashboard name, system name).
        role: Optional role name (reserved for future use).

    Returns:
        A tuple of (anomaly_score, factors), where:
        - anomaly_score is a float in [0.0, 1.0] (higher = more anomalous).
        - factors is a list of human-readable strings explaining the score.
    """
    factors: List[str] = []

    # Fetch all prior accepted requests for this requester.
    prior_accepted = (
        db.query(AccessRequest)
        .filter(
            AccessRequest.requester_id == requester_id,
            AccessRequest.status.in_(
                [
                    RequestStatus.AUTO_APPROVED,
                    RequestStatus.APPROVED,
                ]
            ),
        )
        .all()
    )

    history_count = len(prior_accepted)

    # Cold-start: insufficient history
    if history_count < MIN_HISTORY_FOR_WARM_START:
        logger.info(
            "Requester '%s' has only %d prior accepted request(s); applying cold-start anomaly score %.2f",
            requester_id,
            history_count,
            COLD_START_ANOMALY_SCORE,
        )
        factors.append(
            f"Requester has only {history_count} prior accepted request(s); "
            "insufficient history to establish a baseline. Flagged as higher-anomaly."
        )
        return COLD_START_ANOMALY_SCORE, factors

    # Warm-start: compute deviation based on request_type
    same_type_count = sum(1 for r in prior_accepted if r.classification == request_type)

    # Fraction of prior requests that share the same type
    same_type_fraction = same_type_count / history_count if history_count > 0 else 0.0

    # The anomaly score is the complement of the fraction: if 80% of prior
    # requests were of the same type, the anomaly score is 0.2.
    type_anomaly = 1.0 - same_type_fraction

    # Additional deviation if resource is provided (optional)
    resource_anomaly = 0.0
    if resource:
        # For now, we check if any prior request's request_text contains the resource.
        # This is a simple heuristic; future versions could store resource explicitly.
        resource_lower = resource.lower()
        same_resource_count = sum(
            1 for r in prior_accepted if resource_lower in r.request_text.lower()
        )
        same_resource_fraction = (
            same_resource_count / history_count if history_count > 0 else 0.0
        )
        resource_anomaly = 1.0 - same_resource_fraction

        if resource_anomaly > 0.0:
            factors.append(
                f"Requester has {same_resource_count} prior request(s) mentioning "
                f"'{resource}' out of {history_count} total; "
                f"resource deviation contributes {resource_anomaly:.2f} to the anomaly score."
            )

    # Combine: use max of type and resource anomalies for a simple overall score.
    # Precision capped to 4 decimal places.
    anomaly_score = round(max(type_anomaly, resource_anomaly), 4)

    factors.append(
        f"{same_type_count} of {history_count} prior accepted request(s) were of type "
        f"'{request_type.value}' (fraction {same_type_fraction:.2f}); "
        f"type anomaly contributes {type_anomaly:.2f}."
    )

    logger.info(
        "Anomaly score for requester '%s': %.4f (history=%d, same_type=%d, resource='%s')",
        requester_id,
        anomaly_score,
        history_count,
        same_type_count,
        resource or "None",
    )

    return anomaly_score, factors
