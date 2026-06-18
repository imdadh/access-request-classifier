import logging

from pydantic import ValidationError

from app.llm.protocol import LLMClassifier, ClassificationError
from app.schemas.classification_schema import ClassificationResult

logger = logging.getLogger(__name__)


def classify(provider: LLMClassifier, request_text: str) -> ClassificationResult:
    """Classify a request using the given provider, validate output, and return a validated result.

    Args:
        provider: An object implementing the LLMClassifier protocol.
        request_text: The free-text access request to classify.

    Returns:
        A validated ClassificationResult instance.

    Raises:
        ClassificationError: If the provider call fails or the output fails
            schema validation (e.g., invalid request_type, wrong keys,
            out-of-range confidence).
    """
    raw = provider.classify(request_text)

    try:
        result = ClassificationResult.model_validate(raw)
    except ValidationError as e:
        logger.error("LLM output failed schema validation: %s", e)
        raise ClassificationError(
            f"Classification output failed validation: {e}"
        ) from e

    return result
