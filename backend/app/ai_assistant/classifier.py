"""
app/ai_assistant/classifier.py
──────────────────────────────────────────────────────────────────────────
Default `IntentEngine` implementation: fast, offline, dependency-free
keyword/rule matching. No cloud calls, no paid APIs, nothing to download.

Matching order:
  1. Phrase match — every intent in NAV_KB / DATA_KB carries a list of
     example phrases. If any phrase is a substring of the user's (lower-
     cased) question, that's a strong signal.
  2. Party lookup — trigger phrases like "about X", "who is X",
     "customer X", "vendor X" extract X and route to a live lookup
     against customers / vendors / CRM leads.
  3. Category fallback — loose single keyword buckets (e.g. "stock" →
     low_stock) so common phrasing that wasn't explicitly listed still
     gets routed sensibly.
  4. Bare-name fallback — anything short that isn't a question and
     didn't match anything above is treated as a possible name (e.g.
     someone just typing "Kumar Electronics") and sent to party lookup.

To swap in a real local model later, implement `IntentEngine` (see base.py)
in a new file and change `get_intent_engine()` below to return it — nothing
else in the app needs to know the difference.
"""
from __future__ import annotations

from app.ai_assistant.base import IntentEngine, IntentMatch
from app.ai_assistant.knowledge_base import DATA_KB, NAV_KB

# Loose single-keyword fallback buckets, checked only if no phrase matched.
# Order matters — first match wins.
_CATEGORY_FALLBACK: list[tuple[str, str]] = [
    ("sale", "data.today_sales"),
    ("revenue", "data.today_sales"),
    ("stock", "data.low_stock"),
    ("inventory", "data.low_stock"),
    ("customer", "data.top_customers"),
    ("payment", "data.pending_payments"),
    ("due", "data.pending_payments"),
    ("outstanding", "data.pending_payments"),
    ("purchase order", "nav.purchase_orders"),
    ("vendor", "nav.add_vendor"),
    ("product", "nav.add_product"),
    ("invoice", "nav.new_invoice"),
    ("gst", "nav.gst_reports"),
]

# Trigger phrases that mean "look this name up", e.g. "about X", "customer X".
# Longest/most specific first so "tell me about" strips fully in one pass.
_PARTY_LOOKUP_PREFIXES: list[str] = [
    "tell me about ", "information about ", "information on ",
    "details about ", "details of ", "details on ",
    "who is ", "who's ", "info on ", "info about ",
    "show me ", "show ", "search for ", "search ", "lookup ", "look up ",
    "about ", "customer ", "vendor ", "party ", "lead ",
]

# A message that starts with one of these is a question, not a bare name —
# keeps "why is revenue down" etc. out of the bare-name fallback (stage 4).
_QUESTION_STARTERS = (
    "how ", "what ", "where ", "why ", "when ", "which ", "who ",
    "can ", "could ", "is ", "are ", "do ", "does ", "did ", "should ", "will ",
)


def _extract_party_name(query: str) -> str | None:
    """Strip any number of leading trigger phrases, e.g. 'show me customer X' → 'X'."""
    text = query
    changed = True
    while changed:
        changed = False
        for prefix in _PARTY_LOOKUP_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                changed = True
    return text or None


class RuleBasedIntentEngine:
    """Default, offline IntentEngine — see module docstring."""

    def classify(self, text: str) -> IntentMatch:
        query = (text or "").strip().lower()
        if not query:
            return IntentMatch(intent_id="unknown", intent_type="unknown", confidence=0.0)

        # Stage 1 — explicit phrase match across both knowledge bases.
        best_id: str | None = None
        best_len = 0
        for intent_id, entry in NAV_KB.items():
            for phrase in entry["keywords"]:
                if phrase in query and len(phrase) > best_len:
                    best_id, best_len = intent_id, len(phrase)
        for intent_id, entry in DATA_KB.items():
            for phrase in entry["keywords"]:
                if phrase in query and len(phrase) > best_len:
                    best_id, best_len = intent_id, len(phrase)

        if best_id is not None:
            intent_type = "navigation" if best_id.startswith("nav.") else "data_query"
            return IntentMatch(intent_id=best_id, intent_type=intent_type, confidence=0.9)

        # Stage 2 — explicit "about X / who is X / customer X" style lookups.
        if any(query.startswith(p) for p in _PARTY_LOOKUP_PREFIXES):
            name = _extract_party_name(query)
            if name:
                return IntentMatch(intent_id="party.lookup", intent_type="party_lookup",
                                    confidence=0.85, query=name)

        # Stage 3 — loose single-keyword fallback.
        for keyword, intent_id in _CATEGORY_FALLBACK:
            if keyword in query:
                intent_type = "navigation" if intent_id.startswith("nav.") else "data_query"
                return IntentMatch(intent_id=intent_id, intent_type=intent_type, confidence=0.5)

        # Stage 4 — bare name fallback (e.g. just "Kumar Electronics" or "bhuvanesh").
        if not any(query.startswith(w) for w in _QUESTION_STARTERS) and len(query.split()) <= 5:
            return IntentMatch(intent_id="party.lookup", intent_type="party_lookup",
                                confidence=0.3, query=query)

        return IntentMatch(intent_id="unknown", intent_type="unknown", confidence=0.0)


def get_intent_engine() -> IntentEngine:
    """
    Single factory used by responder.py.
    Swap this to return a different IntentEngine implementation
    (e.g. one backed by a local Gemma/Qwen/Phi model) to upgrade the
    assistant without touching any other file.
    """
    return RuleBasedIntentEngine()