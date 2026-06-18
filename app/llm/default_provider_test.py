import json
import pytest
from unittest.mock import patch, MagicMock

import httpx

from app.llm.default_provider import DefaultLLMProvider
from app.llm.protocol import ClassificationError

# A simple test prompt without any sensitive data
TEST_PROMPT = "Classify: {request_text}"
DUMMY_API_KEY = "sk-test-dummy-key"  # Placeholder, not a real credential


class TestDefaultLLMProviderClassify:
    """Tests for the classify method of DefaultLLMProvider."""

    @pytest.fixture
    def provider(self) -> DefaultLLMProvider:
        """Return a DefaultLLMProvider instance with dummy config."""
        return DefaultLLMProvider(
            prompt=TEST_PROMPT,
            api_key=DUMMY_API_KEY,
            model="gpt-4o-mini",
            endpoint="https://api.openai.com/v1/chat/completions",
        )

    def test_successful_classification_returns_dict(self, provider: DefaultLLMProvider):
        """A 200 response with valid JSON should return the parsed dict."""
        expected_content = {"request_type": "data-access", "confidence": 0.95}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps(expected_content)}}]
        }

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            result = provider.classify("I need access to reports")

        assert result == expected_content

    def test_http_error_raises_classification_error(self, provider: DefaultLLMProvider):
        """A non-200 HTTP status should raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(ClassificationError, match="returned status 500"):
                provider.classify("some request")

    def test_network_error_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """A network-level error should raise ClassificationError."""
        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.side_effect = httpx.RequestError(
                "connection failed"
            )

            with pytest.raises(ClassificationError, match="LLM request failed"):
                provider.classify("some request")

    def test_non_json_response_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """A non-JSON response body should raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError(
            "Expecting value", "<html>", 0
        )

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(ClassificationError, match="non-JSON response"):
                provider.classify("some request")

    def test_missing_choices_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """A response without 'choices' key should raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"error": "something"}

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(
                ClassificationError, match="Unexpected LLM response structure"
            ):
                provider.classify("some request")

    def test_empty_choices_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """An empty choices list should raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(ClassificationError, match="LLM returned no choices"):
                provider.classify("some request")

    def test_invalid_json_in_content_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """If the content field is not valid JSON, raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "not json"}}]
        }

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(ClassificationError, match="is not valid JSON"):
                provider.classify("some request")

    def test_non_dict_content_raises_classification_error(
        self, provider: DefaultLLMProvider
    ):
        """If the parsed JSON is not a dict, raise ClassificationError."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "[1,2,3]"}}]
        }

        with patch.object(httpx, "Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.post.return_value = mock_response

            with pytest.raises(ClassificationError, match="is not a JSON object"):
                provider.classify("some request")
