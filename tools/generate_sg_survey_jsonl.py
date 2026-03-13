#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate DeepResearch eval JSONL for SIPMM's sector survey.

Examples:
  python tools/generate_sg_survey_jsonl.py \
    --this-month "September 2025" \
    --country "Singapore" \
    --output inference/eval_data/sg_survey.jsonl

Accepted --this-month formats:
  "September 2025", "Sep 2025", "2025-09", "09-2025", "09/2025", "2025/09"
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

# -----------------------------
# Static configuration
# -----------------------------

SECTORS: List[str] = [
    "Biomedical Manufacturing (Medical Technology)",
    "Biomedical Manufacturing (Pharmaceutical)",
    "Chemicals Manufacturing (Petroleum & Petrochemicals)",
    "Chemicals Manufacturing (Specialties & Other Chemicals)",
    "Electronics Manufacturing (Non-Semiconductors)",
    "Electronics Manufacturing (Semiconductors)",
    "Precision Engineering Manufacturing",
    "Transport Engineering Manufacturing",
]

@dataclass(frozen=True)
class Indicator:
    name: str      # Descriptive label
    short: str     # Phrase to drop into the prompt
    options: str   # Response options

INDICATORS: List[Indicator] = [
    Indicator("New Orders", "new sales orders", "Higher, No change, or Lower"),
    Indicator("New Export Orders", "new export sales", "Higher, No change, or Lower"),
    Indicator("Output", "factory output", "Higher, No change, or Lower"),
    Indicator("Stocks of Input Purchases", "stocks of input purchases", "Higher, No change, or Lower"),
    Indicator("Stocks of Finished Goods", "stocks of finished goods", "Higher, No change, or Lower"),
    Indicator("Imports", "total imports", "Higher, No change, or Lower"),
    Indicator("Input Prices", "total costs of input materials for production", "Higher, No change, or Lower"),
    Indicator("Employment", "company’s employment strength", "Higher, No change, or Lower"),
    Indicator("Supplier Deliveries", "total supplier deliveries", "Faster, No change, or Slower"),
    Indicator("Backlogs of Orders", "company’s unfulfilled sales orders", "Higher, No change, or Lower"),
    Indicator("Future Business", "expected company’s future manufacturing activity", "Higher, No change, or Lower"),
]

TEMPLATE = (
    "In {country}, what are the companies operate within the {sector} sector, "
    "and how are their {indicator} in {this_month} compared to {last_month}? {options}?"
)

# -----------------------------
# Helpers
# -----------------------------

def parse_this_month(s: str) -> datetime:
    """Parse 'this month' from multiple formats and return first day of that month."""
    s = s.strip()
    for fmt in ("%B %Y", "%b %Y", "%Y-%m", "%m-%Y", "%m/%Y", "%Y/%m"):
        try:
            return datetime.strptime(s, fmt).replace(day=1)
        except ValueError:
            pass
    raise ValueError(
        f"Could not parse --this-month value '{s}'. Try formats like 'September 2025' or '2025-09'."
    )

def prev_month(dt: datetime) -> datetime:
    """Return the first day of the previous month."""
    y, m = dt.year, dt.month
    return dt.replace(year=y-1, month=12, day=1) if m == 1 else dt.replace(month=m-1, day=1)

def month_yyyy(dt: datetime) -> str:
    """Format as 'Month YYYY' (e.g., 'September 2025')."""
    return dt.strftime("%B %Y")

def build_question(country: str, sector: str, indicator: Indicator, this_m: str, last_m: str) -> str:
    return TEMPLATE.format(
        country=country,
        sector=sector,
        indicator=indicator.short,
        this_month=this_m,
        last_month=last_m,
        options=indicator.options,
    )

# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--this-month", required=True, help="Target month (e.g., 'September 2025' or '2025-09').")
    ap.add_argument("--output", required=True, help="Output JSONL path.")
    ap.add_argument("--country", default="Singapore", help="Country name to inject in the question.")
    args = ap.parse_args()

    this_dt = parse_this_month(args.this_month)
    last_dt = prev_month(this_dt)
    this_str = month_yyyy(this_dt)
    last_str = month_yyyy(last_dt)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for sector in SECTORS:
            for ind in INDICATORS:
                q = build_question(args.country, sector, ind, this_str, last_str)
                f.write(json.dumps({"question": q, "answer": ""}, ensure_ascii=False) + "\n")
                count += 1

    print(f"Wrote {count} lines to {out_path}")

if __name__ == "__main__":
    main()
