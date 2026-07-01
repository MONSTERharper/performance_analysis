"""Detect user intent — greeting vs data question."""

from __future__ import annotations

import re

from chatbot.filters import QueryFilters

GREETINGS = {
    "hi", "hello", "hey", "hiya", "howdy", "yo",
    "good morning", "good afternoon", "good evening",
    "thanks", "thank you", "thx",
    "help", "?", "what can you do",
}

DATA_SIGNALS = re.compile(
    r"\b("
    r"plot|chart|graph|show|list|count|average|top|error|stoppage|slide|scan|"
    r"site|cluster|raw|table|export|data|trend|compare|how many|which|when|"
    r"regression|load time|duration|mongo|collection|query|week|day|month"
    r")\b",
    re.I,
)

METRIC_SIGNALS = re.compile(
    r"\b(how many|count|total|top|most|average|avg|list|show me|number of|sum)\b",
    re.I,
)

CONCEPTUAL_SIGNALS = re.compile(
    r"\b("
    r"explain|what does .+ mean|how do .+ relate|difference between|"
    r"which collection|what fields|what is the|describe the schema|help me understand"
    r")\b",
    re.I,
)


def is_greeting_or_smalltalk(message: str) -> bool:
    text = message.strip().lower().rstrip("!?.")
    if not text:
        return True
    if text in GREETINGS:
        return True
    if len(text) < 25 and text.startswith(("hi ", "hey ", "hello ")):
        return True
    # "hi there" etc.
    if len(text) < 30 and re.match(r"^(hi|hey|hello)\b", text):
        return not DATA_SIGNALS.search(text)
    return False


def is_plot_request(message: str) -> bool:
    if is_greeting_or_smalltalk(message):
        return False
    q = message.lower()
    return bool(re.search(r"\b(plot|chart|graph|visualiz|trend)\b", q))


def should_use_builtin_chart(message: str, *, auto_chart_with_data: bool) -> bool:
    """Whether to use reliable built-in Plotly charts instead of LLM plot code."""
    if is_plot_request(message):
        return True
    if not auto_chart_with_data:
        return False
    q = message.lower()
    return bool(
        re.search(
            r"\b(error|errors|slide|slides|stoppage|stoppages|downtime|load time|load duration|regression|scan time)\b",
            q,
        )
    )


def is_data_question(message: str) -> bool:
    if is_greeting_or_smalltalk(message):
        return False
    return bool(DATA_SIGNALS.search(message)) or len(message.strip()) > 40


def requires_database_query(message: str) -> bool:
    """True when the answer must come from MongoDB tools, not LLM memory."""
    if is_greeting_or_smalltalk(message) or is_plot_request(message):
        return False
    if CONCEPTUAL_SIGNALS.search(message) and not METRIC_SIGNALS.search(message):
        return False
    return is_data_question(message)


def greeting_response(filters: QueryFilters | None = None) -> str:
    filter_note = ""
    if filters and filters.is_active():
        filter_note = f"\n\n**Active filters:** {filters.summary()}"

    return f"""Hi! I'm your **scanner performance assistant** for the `test_db2` MongoDB database.

I can help you with:
- **Questions** about errors, stoppages, load times, slide counts, and sites
- **Charts** — e.g. *"plot slides scanned day-wise for the last 5 weeks"*
- **Raw data tables** — e.g. *"show me raw error logs for this site"*
- **Exports** — CSV, JSON, and chart downloads on each response

Ask me anything about your scanner data, or try an example from the sidebar.{filter_note}"""
