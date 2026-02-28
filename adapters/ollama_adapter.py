import json
import re
import time

import requests

from .base import LLMAdapter


class OllamaAdapter(LLMAdapter):
    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434", timeout: int = 600):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str:
        start = time.time()
        last_err = None
        for attempt in range(2):
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                            "num_ctx": 16384,
                        },
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                self.last_usage = {
                    "input_tokens": data.get("prompt_eval_count", 0),
                    "output_tokens": data.get("eval_count", 0),
                    "latency_ms": int((time.time() - start) * 1000),
                }
                return data["message"]["content"]
            except requests.exceptions.ReadTimeout as e:
                last_err = e
                if attempt == 0:
                    import logging
                    logging.getLogger("workflow").warning(
                        f"  Ollama timeout ({self.timeout}s) on attempt {attempt + 1}, retrying..."
                    )
                    time.sleep(2)
        raise last_err

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> dict:
        # For small local models: show required fields as a flat list instead of
        # the full JSON Schema (which they tend to echo back verbatim).
        field_hints = self._schema_to_field_hints(schema)
        prompt_with_schema = (
            f"{user_prompt}\n\n"
            f"Respond with a JSON object containing these fields:\n"
            f"{field_hints}\n\n"
            f"IMPORTANT: Output ONLY the JSON data object with actual values filled in. "
            f"Do NOT output a JSON Schema definition. Do NOT include 'properties', 'type', "
            f"'description', or 'required' keys. Just the data."
        )

        for attempt in range(3):
            text = self.complete(system_prompt, prompt_with_schema, temperature, max_tokens)
            try:
                return self._extract_json(text)
            except (json.JSONDecodeError, ValueError):
                if attempt == 2:
                    raise ValueError(f"Failed to parse JSON after 3 attempts. Last response:\n{text}")

    @staticmethod
    def _schema_to_field_hints(schema: dict) -> str:
        """Convert a JSON Schema into a simple field description list for small models."""
        lines = []
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        for name, prop in props.items():
            # Determine type
            ptype = prop.get("type", "any")
            if "anyOf" in prop:
                types = [t.get("type", "?") for t in prop["anyOf"] if isinstance(t, dict)]
                ptype = " | ".join(t for t in types if t != "null")
                if any(t.get("type") == "null" for t in prop["anyOf"] if isinstance(t, dict)):
                    ptype += " (optional)"

            # Handle nested objects
            if ptype == "object" and "properties" in prop:
                nested = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in prop["properties"].items())
                ptype = f"object {{ {nested} }}"

            # Handle arrays
            if ptype == "array":
                items = prop.get("items", {})
                if "properties" in items:
                    nested = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in items["properties"].items())
                    ptype = f"array of {{ {nested} }}"
                else:
                    ptype = f"array of {items.get('type', 'any')}"

            desc = prop.get("description", "")
            req = "*" if name in required else ""
            line = f"  - {name}{req} ({ptype})"
            if desc:
                line += f": {desc}"
            lines.append(line)

        header = "Fields (* = required):"
        return header + "\n" + "\n".join(lines)

    @staticmethod
    def _extract_json(text: str) -> dict:
        """Extract JSON from model response, handling multiple JSON blocks and thinking tags."""
        cleaned = text.strip()
        # Strip <think>...</think> blocks from reasoning models
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

        # Find all top-level JSON objects by matching balanced braces
        candidates = []
        depth = 0
        start = None
        for i, ch in enumerate(cleaned):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(cleaned[start : i + 1])
                    start = None

        # Parse all candidates, then pick the best one
        parsed = []
        for candidate in candidates:
            try:
                parsed.append(json.loads(candidate))
            except json.JSONDecodeError:
                continue

        if not parsed:
            # Fallback: try the whole text
            return json.loads(cleaned)

        if len(parsed) == 1:
            return parsed[0]

        # Multiple JSON objects found. Filter out JSON Schema definitions
        # (they have "properties" and "type":"object" at top level).
        data_objects = [
            obj for obj in parsed
            if not ("properties" in obj and obj.get("type") == "object")
        ]

        if data_objects:
            return data_objects[-1]  # last non-schema object

        # All objects look like schemas — return the last one as fallback
        return parsed[-1]

    def get_model_name(self) -> str:
        return self.model
