import logging
from typing import List, Optional

from app.config import settings
from app.schemas import RoleMapping

logger = logging.getLogger(__name__)


def route_request(
    anomaly_score: float,
    role_mappings: List[RoleMapping],
    anomaly_threshold: Optional[float] = None,
) -> str:
    """Determine whether to auto-approve or route to manual review.

    Auto-approval requires both:
      - anomaly_score < anomaly_threshold (low anomaly)
      - at least one role mapping exists (confident role mapping)
    Otherwise the request is routed to manual review (pending_review).

    Args:
        anomaly_score: Computed anomaly score in [0.0, 1.0]; lower is less anomalous.
        role_mappings: List of suggested RoleMapping objects from the role mapping
            service. An empty list means no confident role mapping exists.
        anomaly_threshold: Configurable threshold below which the request is
            considered non-anomalous. If not provided, uses the value from
            application settings.

    Returns:
        One of "auto_approved" or "pending_review" indicating the routing decision.
    """
    if anomaly_threshold is None:
        anomaly_threshold = settings.anomaly_threshold

    if anomaly_score < anomaly_threshold and role_mappings:
        logger.info(
            "Request auto-approved: anomaly_score=%.4f < threshold=%.4f, "
            "%d role mapping(s) found",
            anomaly_score,
            anomaly_threshold,
            len(role_mappings),
        )
        return "auto_approved"

    # Build reasons for manual review for observability
    reasons = []
    if anomaly_score >= anomaly_threshold:
        reasons.append(
            f"anomaly score {anomaly_score:.4f} >= threshold {anomaly_threshold:.4f}"
        )
    if not role_mappings:
        reasons.append("no confident role mapping")
    logger.info(
        "Request routed to manual review: %s",
        "; ".join(reasons),
    )
    return "pending_review"
