"""Tests for query_auto — routing + execution with a mocked MongoDB."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import chatbot.query_auto as qa


# --------------------------------------------------------------------------- #
# Routing: try_auto_query should dispatch to the right built-in query
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "question, target",
    [
        ("types of controller card errors", "query_errors_matching"),
        ("controller error breakdown", "query_errors_matching"),
        ("list all collections", "query_collections"),
        ("show me all sites", "query_sites"),
        ("what are the top errors", "query_top_errors"),
        ("any errors?", "query_top_errors"),
        ("how many slides scanned", "query_slide_totals"),
        ("which sites have the most stoppages", "query_stoppages_by_site"),
        ("average load duration by site", "query_load_time_by_site"),
    ],
)
def test_routing(monkeypatch, question, target):
    sentinel = {"success": True, "routed_to": target}
    called = {}

    def fake(*args, **kwargs):
        called["hit"] = True
        return sentinel

    monkeypatch.setattr(qa, target, fake)
    result = qa.try_auto_query(question, None)
    assert called.get("hit"), f"{question!r} did not route to {target}"
    assert result is sentinel


def test_routing_no_match_returns_failure():
    result = qa.try_auto_query("tell me a joke about pathology", None)
    assert result["success"] is False


# --------------------------------------------------------------------------- #
# Execution: values come straight from the mocked aggregate results
# --------------------------------------------------------------------------- #
def _mock_db_with_aggregate(monkeypatch, collection_attr, rows):
    mock_db = MagicMock()
    getattr(mock_db, collection_attr).aggregate.return_value = rows
    monkeypatch.setattr(qa, "_db", lambda: mock_db)
    return mock_db


def test_query_top_errors_uses_real_labels(monkeypatch):
    rows = [
        {"_id": "Sensor timeout", "count": 12},
        {"_id": "Tray jam", "count": 4},
    ]
    _mock_db_with_aggregate(monkeypatch, "Error_counts", rows)

    out = qa.query_top_errors(None)
    assert out["success"]
    assert "Sensor timeout" in out["summary"]
    assert "Tray jam" in out["summary"]
    assert out["raw_data_meta"]["collection"] == "Error_counts"
    # renamed group column
    assert out["raw_data"][0].get("error") == "Sensor timeout"


def test_query_errors_matching_controller(monkeypatch):
    rows = [{"_id": "Controller comms lost", "count": 5}]
    _mock_db_with_aggregate(monkeypatch, "Error_counts", rows)

    out = qa.query_errors_matching(None, text="controller")
    assert out["success"]
    assert "Controller comms lost" in out["summary"]
    # invented label must not sneak in
    assert "Overheating" not in out["summary"]


def test_query_errors_matching_no_rows(monkeypatch):
    mock_db = MagicMock()
    mock_db.Error_counts.aggregate.return_value = []
    mock_db.raw_error_logs.aggregate.return_value = []
    monkeypatch.setattr(qa, "_db", lambda: mock_db)

    out = qa.query_errors_matching(None, text="controller")
    assert out["success"] is False


def test_query_collections(monkeypatch):
    mock_db = MagicMock()
    mock_db.list_collection_names.return_value = ["sites", "Error_counts"]
    mock_db.__getitem__.return_value.estimated_document_count.return_value = 42
    monkeypatch.setattr(qa, "_db", lambda: mock_db)

    out = qa.query_collections()
    assert out["success"]
    assert "sites" in out["summary"]
    assert "Error_counts" in out["summary"]
