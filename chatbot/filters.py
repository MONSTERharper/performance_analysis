"""Site and date filters for scoping chatbot queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

from db.connection import get_database


@dataclass
class QueryFilters:
    site_key: str | None = None
    site_name: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    apply_site: bool = False
    apply_dates: bool = False

    def mongo_filter(self) -> dict:
        """Build MongoDB filter clauses from active sidebar filters."""
        clauses: dict = {}
        if self.apply_site and self.site_key:
            clauses["site_key"] = self.site_key
        if self.apply_dates:
            if self.date_start and self.date_end:
                clauses["date_str"] = {
                    "$gte": self.date_start.isoformat(),
                    "$lte": self.date_end.isoformat(),
                }
            elif self.date_start:
                clauses["date_str"] = {"$gte": self.date_start.isoformat()}
            elif self.date_end:
                clauses["date_str"] = {"$lte": self.date_end.isoformat()}
        return clauses

    def merge_filter(self, user_filter: dict | None) -> dict:
        """Merge sidebar filters with a tool-provided filter."""
        merged = dict(user_filter or {})
        for key, value in self.mongo_filter().items():
            if key not in merged:
                merged[key] = value
            elif key == "date_str" and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = {**value, **merged[key]}
        return merged

    def to_prompt_context(self) -> str:
        if not self.is_active():
            return ""
        parts = ["## Active Sidebar Filters (ALWAYS apply to queries unless user explicitly asks for all sites/dates)"]
        if self.apply_site and self.site_key:
            parts.append(f"- Site: `{self.site_name}` (site_key: `{self.site_key}`)")
        elif self.apply_site:
            parts.append("- Site: All sites")
        if self.apply_dates and self.date_start and self.date_end:
            parts.append(f"- Date range: `{self.date_start}` to `{self.date_end}` (use `date_str` field)")
        elif self.apply_dates:
            parts.append("- Date range: No date restriction")
        parts.append("- Include these filters in every `find_documents`, `aggregate`, `fetch_raw_data`, and `generate_plot` call.")
        return "\n".join(parts)

    def is_active(self) -> bool:
        site_active = self.apply_site and bool(self.site_key)
        date_active = self.apply_dates and bool(self.date_start or self.date_end)
        return site_active or date_active

    def summary(self) -> str:
        bits = []
        if self.apply_site and self.site_name:
            bits.append(self.site_name)
        elif self.apply_site and self.site_key:
            bits.append(self.site_key)
        if self.apply_dates and self.date_start and self.date_end:
            bits.append(f"{self.date_start} → {self.date_end}")
        return " · ".join(bits) if bits else "No filters"


@lru_cache(maxsize=1)
def load_sites() -> list[dict]:
    db = get_database("test_db2")
    sites = list(db.sites.find({}, {"site_key": 1, "site_name": 1, "_id": 0}).sort("site_name", 1))
    return sites


def default_date_range(weeks: int = 5) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(weeks=weeks)
    return start, end
