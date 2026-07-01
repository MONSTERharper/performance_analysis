"""Sandboxed Python execution for generating Plotly charts from MongoDB data."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from db.connection import get_database

DATABASE = "test_db2"

BLOCKED_PATTERNS = [
    "import os",
    "import subprocess",
    "import shutil",
    "import socket",
    "import sys",
    "open(",
    "exec(",
    "eval(",
    "__import__",
    "compile(",
    "globals(",
    "locals(",
    "breakpoint(",
    "input(",
]

SAFE_BUILTINS = {
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "print": print,
    "isinstance": isinstance,
    "any": any,
    "all": all,
}


def _build_namespace() -> dict[str, Any]:
    return {
        "pd": pd,
        "px": px,
        "go": go,
        "datetime": datetime,
        "timedelta": timedelta,
        "get_database": lambda: get_database(DATABASE),
        "DATABASE": DATABASE,
    }


def execute_plot_code(code: str) -> dict:
    """
    Execute analysis/plotting code in a restricted namespace.
    Code must assign a Plotly figure to variable `fig`.
    """
    for pattern in BLOCKED_PATTERNS:
        if pattern in code:
            return {"success": False, "error": f"Blocked pattern in code: {pattern}"}

    namespace = _build_namespace()
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(code, {"__builtins__": SAFE_BUILTINS}, namespace)

        fig = namespace.get("fig")
        if fig is None:
            return {
                "success": False,
                "error": "Code must assign a Plotly figure to variable `fig`.",
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            }

        return {
            "success": True,
            "figure_json": pio.to_json(fig),
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
        }


PLOT_CODE_TEMPLATE = '''
# Example: day-wise slides scanned (last 5 weeks)
from datetime import datetime, timedelta

db = get_database()
cutoff = (datetime.now() - timedelta(weeks=5)).strftime("%Y-%m-%d")

docs = list(db.slide_count_values.find(
    {"date_str": {"$gte": cutoff}},
    {"date_str": 1, "Specified cycle slides scanned": 1, "_id": 0},
))
df = pd.DataFrame(docs)
df["slides"] = pd.to_numeric(df["Specified cycle slides scanned"], errors="coerce").fillna(0)
daily = df.groupby("date_str", as_index=False)["slides"].sum().sort_values("date_str")

fig = px.line(daily, x="date_str", y="slides", title="Total Slides Scanned per Day (Last 5 Weeks)")
fig.update_layout(xaxis_title="Date", yaxis_title="Slides Scanned")
'''
