"""Tests for grounded_summary — the fix for post-query hallucination.

The model must never rename or invent values; answers come from tool JSON.
"""

from __future__ import annotations

from chatbot.grounded_summary import (
    extract_raw_payload,
    format_grounded_answer,
    has_groundable_data,
)


def test_aggregate_answer_uses_real_values_only():
    tool_results = [
        ("aggregate", {
            "collection": "Error_counts",
            "results": [
                {"_id": "Real DB Error A", "count": 5},
                {"_id": "Real DB Error B", "count": 3},
            ],
        }),
    ]
    assert has_groundable_data(tool_results)
    text = format_grounded_answer(tool_results)
    assert "Real DB Error A" in text
    assert "Real DB Error B" in text
    # a plausible hallucinated label must not appear
    assert "Controller Card Overheating" not in text
    # explicit disclaimer that values are not paraphrased
    assert "not paraphrased" in text.lower()


def test_count_documents_formatting():
    tool_results = [("count_documents", {"collection": "sites", "count": 23})]
    text = format_grounded_answer(tool_results)
    assert "23" in text
    assert "sites" in text


def test_documents_formatting_reports_truncation():
    tool_results = [
        ("fetch_raw_data", {
            "collection": "scanner_stoppages",
            "documents": [{"site": "A", "diff": 1}],
            "returned": 1,
            "total_matching": 500,
            "truncated": True,
        }),
    ]
    text = format_grounded_answer(tool_results)
    assert "scanner_stoppages" in text
    assert "500" in text


def test_error_result_is_surfaced_not_hidden():
    tool_results = [("aggregate", {"error": "Collection 'foo' not found"})]
    assert not has_groundable_data(tool_results)
    text = format_grounded_answer(tool_results)
    assert "not found" in text


def test_no_data_returns_none():
    assert format_grounded_answer([("aggregate", {"results": []})]) is None
    assert not has_groundable_data([("aggregate", {"results": []})])


def test_extract_raw_payload_prefers_latest_documents():
    tool_results = [
        ("aggregate", {"collection": "Error_counts", "results": [{"_id": "x", "count": 1}]}),
        ("fetch_raw_data", {
            "collection": "sites",
            "documents": [{"site_key": "a"}],
            "returned": 1,
            "total_matching": 1,
        }),
    ]
    raw, meta = extract_raw_payload(tool_results)
    assert raw == [{"site_key": "a"}]
    assert meta["collection"] == "sites"
