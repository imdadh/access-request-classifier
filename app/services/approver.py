import logging
from typing import List

from app.config import settings
from app.schemas import RoleMapping

logger = logging.getLogger(__name__)


def resolve_approver(role_mappings: List[RoleMapping]) -> str:
    """Recommend an approver for the access request.

    Uses the owner of the highest-confidence role mapping if one exists,
    otherwise falls back to a configurable default reviewer queue.

    Args:
        role_mappings: Sorted list of RoleMapping from best match to lowest.
            May be empty if no roles matched the request.

    Returns:
        A string identifier for the recommended approver (email or queue name).
    """
    if role_mappings:
        approver = role_mappings[0].owner
        logger.info(
            "Resolved approver '%s' from role mapping '%s' (confidence %.4f)",
            approver,
            role_mappings[0].role_name,
            role_mappings[0].confidence,
        )
        return approver

    logger.info(
        "No role mappings found; falling back to default reviewer queue '%s'",
        settings.default_reviewer_queue,
    )
    return settings.default_reviewer_queue
