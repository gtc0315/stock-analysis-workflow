from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    """Abstract interface for LLM providers. Swap models without changing workflow."""

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        """Send a prompt and get a text response."""
        pass

    @abstractmethod
    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> dict:
        """Send a prompt and get a structured JSON response.
        Should handle retries if JSON parsing fails."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier for logging and eval tracking."""
        pass
