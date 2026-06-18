import pytest
from unittest.mock import Mock, create_autospec

from app.llm.classifier import classify, AMBIGUITY_CONFIDENCE_THRESHOLD
from app.llm.protocol import LLMClassifier, ClassificationError
from app.schemas.classification_schema import ClassificationResult
from app.db.models import RequestType


@pytest.fixture
def mock_provider() -> Mock:
    """Return a mock that conforms to the LLMClassifier protocol."""
    return create_autospec(LLMClassifier, instance=True)


class TestClassifySuccess:
    """Tests for the happy path where the provider returns a valid result."""

    def test_returns_valid_classification_result(self, mock_provider: Mock):
        """A valid dict from the provider should yield a ClassificationResult."""
        mock_provider.classify.return_value = {
            "request_type": "data-access",
            "confidence": 0.95,
        }
        result = classify(mock_provider, "I need to view reports")
        assert isinstance(result, ClassificationResult)
        assert result.request_type == RequestType.DATA_ACCESS
        assert result.confidence == 0.95


class TestClassifySchemaFailure:
    """Tests for schema validation failures (invalid enum, extra keys, missing keys, out-of-range confidence)."""

    def test_raises_classification_error_when_request_type_invalid(
        self, mock_provider: Mock
    ):
        """An invalid enum value should raise ClassificationError."""
        mock_provider.classify.return_value = {
            "request_type": "invalid-type",
            "confidence": 0.8,
        }
        with pytest.raises(
            ClassificationError, match="Classification output failed validation"
        ):
            classify(mock_provider, "some request")

    def test_raises_classification_error_when_confidence_out_of_range(
        self, mock_provider: Mock
    ):
        """Confidence outside [0,1] should raise ClassificationError."""
        mock_provider.classify.return_value = {
            "request_type": "data-access",
            "confidence": 1.5,
        }
        with pytest.raises(
            ClassificationError, match="Classification output failed validation"
        ):
            classify(mock_provider, "some request")

    def test_raises_classification_error_when_extra_keys_present(
        self, mock_provider: Mock
    ):
        """Extra keys in the response should raise ClassificationError."""
        mock_provider.classify.return_value = {
            "request_type": "data-access",
            "confidence": 0.9,
            "unexpected": "value",
        }
        with pytest.raises(
            ClassificationError, match="Classification output failed validation"
        ):
            classify(mock_provider, "some request")

    def test_raises_classification_error_when_missing_request_type(
        self, mock_provider: Mock
    ):
        """Missing required fields raise a validation error."""
        mock_provider.classify.return_value = {
            "confidence": 0.9,
        }
        with pytest.raises(
            ClassificationError, match="Classification output failed validation"
        ):
            classify(mock_provider, "some request")


class TestClassifyAmbiguity:
    """Tests for the ambiguity rule (confidence below threshold)."""

    def test_raises_classification_error_when_confidence_below_threshold(
        self, mock_provider: Mock
    ):
        """A valid schema but low confidence should raise a ClassificationError."""
        mock_provider.classify.return_value = {
            "request_type": "data-access",
            "confidence": AMBIGUITY_CONFIDENCE_THRESHOLD - 0.1,
        }
        with pytest.raises(ClassificationError, match="below the ambiguity threshold"):
            classify(mock_provider, "some request")

    def test_raises_classification_error_when_confidence_at_zero(
        self, mock_provider: Mock
    ):
        """Zero confidence should also be flagged as ambiguous."""
        mock_provider.classify.return_value = {
            "request_type": "data-access",
            "confidence": 0.0,
        }
        with pytest.raises(ClassificationError, match="below the ambiguity threshold"):
            classify(mock_provider, "some request")


class TestClassifyProviderErrors:
    """Tests for errors raised by the provider itself (not schema-related)."""

    def test_propagates_classification_error_from_provider(self, mock_provider: Mock):
        """If the provider raises a ClassificationError, it should be re-raised."""
        mock_provider.classify.side_effect = ClassificationError("API unavailable")
        with pytest.raises(ClassificationError, match="API unavailable"):
            classify(mock_provider, "some request")
