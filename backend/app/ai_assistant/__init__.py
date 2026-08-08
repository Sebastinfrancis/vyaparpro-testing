"""
app/ai_assistant
──────────────────────────────────────────────────────────────────────────
Self-contained, offline AI Assistant module for VyaparPro.

Public surface (this is what the rest of the app is allowed to import):

    from app.ai_assistant.responder import get_assistant_response

Everything else in this package (classifier.py, knowledge_base.py,
data_queries.py, base.py) is an internal implementation detail and can be
changed or replaced — including swapping the rule-based classifier for a
real local model (Gemma/Qwen/Phi) — without touching any other part of
the application.
"""
from app.ai_assistant.responder import AssistantResponse, get_assistant_response

__all__ = ["AssistantResponse", "get_assistant_response"]
