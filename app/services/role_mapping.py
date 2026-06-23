import logging
import re
from typing import List

from sqlalchemy.orm import Session

from app.db.models import Role
from app.schemas import RoleMapping
from app.db.models import RequestType

logger = logging.getLogger(__name__)

# Simple stopwords set to ignore common filler words in matching
_STOPWORDS: set[str] = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "in",
    "on",
    "and",
    "or",
    "is",
    "i",
    "need",
    "access",
    "please",
    "grant",
    "me",
    "with",
    "my",
    "that",
    "this",
    "be",
    "have",
    "do",
    "will",
    "would",
    "can",
    "could",
    "should",
    "want",
    "able",
    "view",
    "read",
    "write",
    "use",
    "log",
    "into",
    "get",
    "give",
    "make",
    "set",
    "up",
    "so",
    "to",
    "for",
    "the",
    "a",
    "an",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, return list of meaningful tokens."""
    # Split on every non-alphanumeric boundary (including '-' and '.') so that
    # hyphenated catalog names like "production-database" tokenize into their
    # component words and can match request terms such as "database".
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _compute_confidence(
    request_tokens: list[str], role_name: str, resource: str
) -> float:
    """Return a confidence score in [0,1] based on token overlap with role name and resource."""
    if not request_tokens:
        return 0.0
    name_tokens = _tokenize(role_name)
    resource_tokens = _tokenize(resource)
    combined_tokens = set(name_tokens + resource_tokens)
    if not combined_tokens:
        return 0.0
    matches = sum(1 for tok in request_tokens if tok in combined_tokens)
    # Jaccard-like: matches / union size
    union = len(set(request_tokens) | combined_tokens)
    return round(matches / max(union, 1), 4)


def map_roles(
    db: Session,
    request_text: str,
    request_type: RequestType,  # may be used for filtering in future improvements
) -> List[RoleMapping]:
    """Suggest catalog roles that satisfy the access request.

    Queries all roles from the database, computes a relevance/confidence score
    by token overlap between the request text and each role's name and resource.
    Returns a list of :class:`RoleMapping` sorted by descending confidence.
    If no role achieves a non‑zero score, returns an empty list.

    Args:
        db: Active database session.
        request_text: The free‑text request from the user.
        request_type: The classified request type (currently unused but retained
            for future filtering).

    Returns:
        List of RoleMapping entries, each containing role name, resource, owner,
        and a confidence score between 0.0 and 1.0. Sorted high‑confidence first.
        Empty if no roles match.
    """
    roles = db.query(Role).all()
    if not roles:
        logger.info("No roles found in catalog; returning empty mapping.")
        return []

    request_tokens = _tokenize(request_text)
    if not request_tokens:
        logger.warning(
            "Request text produced no meaningful tokens; returning empty mapping."
        )
        return []

    scored: list[tuple[float, Role]] = []
    for role in roles:
        confidence = _compute_confidence(request_tokens, role.name, role.resource)
        if confidence > 0.0:
            scored.append((confidence, role))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Build result list, taking at most the top 5 matches to keep response concise
    max_suggestions = 5
    mappings = [
        RoleMapping(
            role_name=role.name,
            resource=role.resource,
            owner=role.owner,
            confidence=confidence,
        )
        for confidence, role in scored[:max_suggestions]
    ]

    if not mappings:
        logger.info("No role matched the request; returning empty mapping.")
    else:
        logger.info(
            "Role mapping generated %d suggestion(s) (top confidence: %.4f).",
            len(mappings),
            mappings[0].confidence,
        )

    return mappings
