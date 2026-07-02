"""Tests for QueryFilters — opt-in behavior and Mongo clause building."""

from __future__ import annotations

from datetime import date

from chatbot.filters import QueryFilters


def test_default_filters_are_inactive():
    f = QueryFilters()
    assert not f.is_active()
    assert f.mongo_filter() == {}
    assert f.to_prompt_context() == ""
    assert f.summary() == "No filters"


def test_site_filter_only_active_with_key():
    assert not QueryFilters(apply_site=True).is_active()
    f = QueryFilters(apply_site=True, site_key="stanford--stanford--001", site_name="Stanford")
    assert f.is_active()
    assert f.mongo_filter() == {"site_key": "stanford--stanford--001"}
    assert "Stanford" in f.summary()


def test_date_filter_builds_range():
    f = QueryFilters(apply_dates=True, date_start=date(2026, 1, 1), date_end=date(2026, 2, 1))
    assert f.is_active()
    assert f.mongo_filter() == {
        "date_str": {"$gte": "2026-01-01", "$lte": "2026-02-01"}
    }


def test_merge_filter_preserves_user_clause():
    f = QueryFilters(apply_site=True, site_key="k", site_name="n")
    merged = f.merge_filter({"error": "boom"})
    assert merged == {"error": "boom", "site_key": "k"}


def test_merge_filter_user_date_wins_but_keeps_bounds():
    f = QueryFilters(apply_dates=True, date_start=date(2026, 1, 1), date_end=date(2026, 2, 1))
    merged = f.merge_filter({"date_str": {"$gte": "2026-01-15"}})
    # user's explicit gte overrides, sidebar lte is still merged in
    assert merged["date_str"]["$gte"] == "2026-01-15"
    assert merged["date_str"]["$lte"] == "2026-02-01"


def test_prompt_context_only_when_active():
    active = QueryFilters(apply_site=True, site_key="k", site_name="Nice Site")
    ctx = active.to_prompt_context()
    assert "Nice Site" in ctx
    assert "site_key" in ctx
