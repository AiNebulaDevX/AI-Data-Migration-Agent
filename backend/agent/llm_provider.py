from __future__ import annotations

import abc
import json
from typing import Any, Optional

import httpx

from backend.config import settings
from backend.mapping.confidence import rank_target_candidates
from backend.models.schemas import FieldMappingCandidate, TargetSchemaField


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def suggest_field_mappings(
        self,
        source_columns: list[str],
        target_fields: dict[str, TargetSchemaField],
        samples: dict[str, list[str]],
    ) -> dict[str, Any]:
        """Return structured mapping suggestions with rationale."""


class OpenSourceLLMProvider(LLMProvider):
    async def suggest_field_mappings(
        self,
        source_columns: list[str],
        target_fields: dict[str, TargetSchemaField],
        samples: dict[str, list[str]],
    ) -> dict[str, Any]:
        prompt = {
            "task": "Map source HR columns to target employee schema",
            "source_columns": source_columns,
            "target_fields": list(target_fields.keys()),
            "samples": samples,
            "output_format": {
                "mappings": [
                    {
                        "source_column": "string",
                        "target_field": "string or null",
                        "confidence": "0-1 float",
                        "reason": "string",
                    }
                ]
            },
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={
                        "model": settings.ollama_model,
                        "prompt": (
                            "You are a data migration assistant. Respond with JSON only.\n"
                            + json.dumps(prompt)
                        ),
                        "stream": False,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data.get("response", "{}")
                return json.loads(text)
        except Exception:
            fallback = DeterministicFallbackLLMProvider()
            result = await fallback.suggest_field_mappings(source_columns, target_fields, samples)
            result["provider"] = "deterministic_fallback_after_ollama_error"
            return result


class DeterministicFallbackLLMProvider(LLMProvider):
    """Used when Ollama is unavailable — still uses confidence engine, not hidden rules."""

    async def suggest_field_mappings(
        self,
        source_columns: list[str],
        target_fields: dict[str, TargetSchemaField],
        samples: dict[str, list[str]],
    ) -> dict[str, Any]:
        mappings = []
        for col in source_columns:
            candidates, _incompatible = rank_target_candidates(col, target_fields, samples.get(col, []))
            top = candidates[0] if candidates else None
            mappings.append(
                {
                    "source_column": col,
                    "target_field": top.target_field if top else None,
                    "confidence": top.confidence if top else 0.0,
                    "reason": "; ".join(top.reasons[:2]) if top else "No match",
                    "candidates": [c.model_dump() for c in candidates[:3]],
                }
            )
        return {"mappings": mappings, "provider": "deterministic_fallback"}


async def _ollama_model_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            if r.status_code != 200:
                return False
            names = [m.get("name", "") for m in r.json().get("models", [])]
            wanted = settings.ollama_model.split(":")[0]
            return any(n == settings.ollama_model or n.split(":")[0] == wanted for n in names)
    except Exception:
        return False


async def get_llm_provider() -> LLMProvider:
    if await _ollama_model_available():
        return OpenSourceLLMProvider()
    return DeterministicFallbackLLMProvider()
