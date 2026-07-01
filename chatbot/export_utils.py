"""Export helpers for charts, raw data, and response text."""

from __future__ import annotations

import json
from io import BytesIO, StringIO
from typing import Any

import pandas as pd
import plotly.io as pio


def records_to_csv(records: list[dict]) -> str:
    if not records:
        return ""
    return pd.DataFrame(records).to_csv(index=False)


def records_to_json(records: list[dict]) -> str:
    return json.dumps(records, indent=2, default=str)


def figure_to_html(figure_json: str) -> str:
    fig = pio.from_json(figure_json)
    return pio.to_html(fig, full_html=True, include_plotlyjs="cdn")


def figure_to_png_bytes(figure_json: str) -> bytes | None:
    try:
        fig = pio.from_json(figure_json)
        return fig.to_image(format="png", width=1200, height=700, scale=2)
    except Exception:
        return None


def content_to_txt(content: str) -> str:
    return content
