"""Tests for intent detection — greeting vs plot vs grounded DB query."""

from __future__ import annotations

import pytest

from chatbot.intent import (
    is_data_question,
    is_greeting_or_smalltalk,
    is_plot_request,
    requires_database_query,
    should_use_builtin_chart,
)


@pytest.mark.parametrize("msg", ["hi", "hello", "hey there", "thanks", "help", "  Hi!  "])
def test_greetings_detected(msg):
    assert is_greeting_or_smalltalk(msg)


@pytest.mark.parametrize(
    "msg",
    ["what are the top errors?", "plot slides day-wise", "how many stoppages at Stanford"],
)
def test_non_greetings(msg):
    assert not is_greeting_or_smalltalk(msg)


@pytest.mark.parametrize(
    "msg", ["plot slides day-wise", "show me a chart of errors", "load time trend", "graph it"]
)
def test_plot_requests(msg):
    assert is_plot_request(msg)


@pytest.mark.parametrize("msg", ["hi", "what are the top errors?", "list all sites"])
def test_non_plot_requests(msg):
    assert not is_plot_request(msg)


@pytest.mark.parametrize(
    "msg",
    [
        "what are the top error codes?",
        "how many slides scanned at Stanford",
        "list all sites",
        "types of controller card errors",
        "which site has the most stoppages",
    ],
)
def test_requires_db_true_for_metric_questions(msg):
    assert requires_database_query(msg)


@pytest.mark.parametrize(
    "msg",
    [
        "hi",
        "plot slides day-wise",
        "how do scanner_stoppages relate to raw_error_logs",
        "explain what site_key means",
    ],
)
def test_requires_db_false(msg):
    assert not requires_database_query(msg)


def test_conceptual_with_metric_still_requires_db():
    # "how many" (metric) overrides the conceptual guard
    assert requires_database_query("explain how many errors there are")


def test_should_use_builtin_chart():
    # explicit plot always uses built-in
    assert should_use_builtin_chart("plot errors", auto_chart_with_data=False)
    # data keyword only counts when auto-chart is enabled
    assert should_use_builtin_chart("top errors", auto_chart_with_data=True)
    assert not should_use_builtin_chart("top errors", auto_chart_with_data=False)
    # unrelated question never charts, even with auto-chart on
    assert not should_use_builtin_chart("list all sites", auto_chart_with_data=True)


def test_is_data_question_long_text():
    assert is_data_question("x" * 60)
    assert not is_data_question("hi")
