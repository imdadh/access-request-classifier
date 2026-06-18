import json
import logging

import httpx

from app.config import settings
from app.llm.protocol import ClassificationError

logger = logging.getLogger(__name__)


class DefaultLLMProvider:
    """Default hosted LLM provider adapter implementing the LLMClassifier protocol.

    Uses OpenAI's ChatGPT API (or compatible endpoint) with the classification
    prompt loaded from the versioned prompt file. The provider is selected via
    the ``LLM_PROVIDER`` configuration value; "default" maps to this class.

    The prompt file must contain the placeholder ``{request_text}``, which is
    replaced at call time with the actual request text. The provider expects the
    LLM to return valid JSON conforming to the ``ClassificationResult`` schema.
    """

    def __init__(
        self,
        prompt: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        endpoint: str = "https://api.openai.com/v1/chat/completions",
    ) -> None:
        """Initialize the provider.

        Args:
            prompt: The full classification prompt with a ``{request_text}``
                placeholder.
            api_key: API key for the hosted LLM provider.
            model: Model identifier (default ``gpt-4o-mini``).
            endpoint: API endpoint URL (default OpenAI chat completions).
        """
        self._prompt = prompt
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint

    @classmethod
    def create_default(cls) -> "DefaultLLMProvider":
        """Factory method that reads the prompt from the known file and
        retrieves the API key from application settings."""
        prompt_path = "app/llm/prompts/classification_prompt.txt"
        try:
            with open(prompt_path, encoding="utf-8") as f:
                prompt = f.read()
        except FileNotFoundError as e:
            raise ClassificationError(
                f"Classification prompt not found at {prompt_path}"
            ) from e

        api_key = settings.llm_api_key.get_secret_value()
        if not api_key:
            raise ClassificationError("LLM API key is not configured")

        return cls(prompt=prompt, api_key=api_key)

    def classify(self, request_text: str) -> dict:
        """Classify the given request text by calling the hosted LLM.

        Args:
            request_text: The raw free-text access request.

        Returns:
            A dictionary containing at least ``request_type`` and ``confidence``
            keys as defined by the classification schema.

        Raises:
            ClassificationError: If the LLM call fails, returns invalid JSON,
                or returns a non-200 status.
        """
        # Substitute the request text into the prompt
        formatted_prompt = self._prompt.replace("{request_text}", request_text)

        messages = [
            {"role": "system", "content": formatted_prompt},
            {"role": "user", "content": request_text},
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.0,  # deterministic output
            "max_tokens": 150,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.info("Calling LLM provider (model=%s) for classification", self._model)

        try:
            with httpx.Client() as client:
                response = client.post(
                    self._endpoint,
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )
        except httpx.RequestError as e:
            raise ClassificationError(f"LLM request failed: {e}") from e

        if response.status_code != 200:
            raise ClassificationError(
                f"LLM returned status {response.status_code}: {response.text[:500]}"
            )

        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            raise ClassificationError(
                f"LLM returned non-JSON response: {response.text[:500]}"
            ) from e

        # Extract the assistant's message content
        try:
            choices = response_data["choices"]
            if not choices:
                raise ClassificationError("LLM returned no choices")
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ClassificationError(f"Unexpected LLM response structure: {e}") from e

        # Parse the JSON inside the content (the LLM may wrap in markdown but
        # we instruct it to output only JSON; accept the most likely format)
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            raise ClassificationError(
                f"LLM output is not valid JSON: {content[:500]}"
            ) from e

        if not isinstance(result, dict):
            raise ClassificationError(
                f"LLM output is not a JSON object: {content[:500]}"
            )

        logger.info(
            "Classification succeeded: type=%s, confidence=%s",
            result.get("request_type"),
            result.get("confidence"),
        )

        return result
