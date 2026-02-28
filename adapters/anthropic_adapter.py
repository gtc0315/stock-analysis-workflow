import json
import os
import time

import anthropic

from .base import LLMAdapter


class AnthropicAdapter(LLMAdapter):
    def __init__(self, model: str = "claude-sonnet-4-5-20250929", api_key_env: str = "ANTHROPIC_API_KEY"):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"Environment variable {api_key_env} is not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        start = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        self.last_usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "latency_ms": int((time.time() - start) * 1000),
        }
        return response.content[0].text

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> dict:
        prompt_with_schema = (
            f"{user_prompt}\n\n"
            f"You MUST respond with valid JSON matching this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n"
            f"Respond ONLY with the JSON object, no other text."
        )

        for attempt in range(3):
            text = self.complete(system_prompt, prompt_with_schema, temperature, max_tokens)
            try:
                # Strip markdown code fences if present
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    first_newline = cleaned.index("\n")
                    cleaned = cleaned[first_newline + 1 :]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                return json.loads(cleaned.strip())
            except (json.JSONDecodeError, ValueError):
                if attempt == 2:
                    raise ValueError(f"Failed to parse JSON after 3 attempts. Last response:\n{text}")

    def get_model_name(self) -> str:
        return self.model
