from typing import Protocol


class ClassificationError(Exception):
    """Raised when an LLM classifier call fails or returns invalid output."""

    pass


class LLMClassifier(Protocol):
    """Provider-agnostic protocol for an LLM-based request classifier.

    Implementations must provide a ``classify`` method that takes a free-text
    access request and returns a dictionary representing the structured
    output from the model. The dictionary is expected to conform to the
    classification schema defined elsewhere; validation is performed by the
    caller.

    The protocol deliberately avoids coupling to any specific vendor SDK or
    transport mechanism. Provider implementations can use HTTP calls, local
    model inference, or any other strategy.
    """

    def classify(self, request_text: str) -> dict:
        """Classify the given request text and return structured output.

        Args:
            request_text: The raw free-text access request.

        Returns:
            A dictionary containing the classification result. The exact keys
            are defined by the classification schema (see
            ``app.schemas.classification_schema``). At minimum, it should
            include the classified type and confidence.

        Raises:
            ClassificationError: If the LLM call fails or returns invalid
                output. (The caller should handle this and treat it as a
                classification failure.)
        """
        ...
