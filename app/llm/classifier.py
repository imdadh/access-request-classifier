import logging

from pydantic import ValidationError

from app.llm.protocol import LLMClassifier, ClassificationError
from app.schemas.classification_schema import ClassificationResult

logger = logging.getLogger(__name__)

# Threshold below which a classification is considered too ambiguous for auto-processing.
# Requests with confidence below this value will be flagged for manual review.
AMBIGUITY_CONFIDENCE_THRESHOLD = 0.5


def classify(provider: LLMClassifier, request_text: str) -> ClassificationResult:
    """Classify a request using the given provider, validate output, and return a validated result.

    Args:
        provider: An object implementing the LLMClassifier protocol.
        request_text: The free-text access request to classify.

    Returns:
        A validated ClassificationResult instance.

    Raises:
        ClassificationError: If the provider call fails, the output fails
            schema validation (e.g., invalid request_type, wrong keys,
            out-of-range confidence), or the model's confidence is below
            the defined ambiguity threshold, indicating the request is
            too ambiguous for automatic classification.
    """
    raw = provider.classify(request_text)

    try:
        result = ClassificationResult.model_validate(raw)
    except ValidationError as e:
        logger.error("LLM output failed schema validation: %s", e)
        raise ClassificationError(
            f"Classification output failed validation: {e}"
        ) from e

    # Ambiguity rule: if confidence is too low, treat as a classification failure
    # and route to manual review rather than guessing.
    if result.confidence < AMBIGUITY_CONFIDENCE_THRESHOLD:
        logger.warning(
            "Classification confidence %.2f below threshold %.2f for request: %s",
            result.confidence,
            AMBIGUITY_CONFIDENCE_THRESHOLD,
            request_text[:100],
        )
        raise ClassificationError(
            f"Classification confidence {result.confidence:.2f} is below the "
            f"ambiguity threshold of {AMBIGUITY_CONFIDENCE_THRESHOLD}. "
            "Request flagged for manual review."
        )

    return result
