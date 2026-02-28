import json
import os
import time

import openai

from .base import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    def __init__(self, model: str = "gpt-4o", api_key_env: str = "OPENAI_API_KEY"):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"Environment variable {api_key_env} is not set")
        self.client = openai.OpenAI(api_key=api_key)
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
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        usage = response.usage
        self.last_usage = {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "latency_ms": int((time.time() - start) * 1000),
        }
        return response.choices[0].message.content

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
