"""
app/ai_assistant/base.py
──────────────────────────────────────────────────────────────────────────
Pluggable interface for the offline AI Assistant.

Everything the rest of VyaparPro touches goes through `IntentEngine`.
Today, `classifier.py` implements it with simple rule/keyword matching
(zero dependencies, runs instantly, no model download).

Later, if you want to swap in a real local model (Gemma, Qwen, Phi, etc. via
llama.cpp / Ollama / ONNX Runtime), you only need to:
  1. Write a new class in this package that implements `IntentEngine`.
  2. Point `get_intent_engine()` in `classifier.py` at your new class.

No other file in the application needs to change — the API endpoint,
the data-query layer and the frontend only ever talk to `responder.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IntentMatch:
    """Result of classifying a user's free-text question."""

    intent_id: str          # e.g. "nav.add_customer" or "data.today_sales"
    intent_type: str        # "navigation" | "data_query" | "party_lookup" | "unknown"
    confidence: float       # 0.0–1.0 (rule engine returns coarse buckets)
    query: str | None = None  # extracted free-text payload, e.g. a name for party_lookup


class IntentEngine(Protocol):
    """Anything that can look at free text and decide what the user wants."""

    def classify(self, text: str) -> IntentMatch:
        """Return the best-guess intent for the given user message."""
        ...
