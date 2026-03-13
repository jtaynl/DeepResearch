#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Export sector-level Markdown files that aggregate ALL iterations' <answer>...</answer>
for the 11 questions, in the required order.

Inputs (auto-detected):
  inference/outputs/*/eval_data/my_questions.jsonl/iter*.jsonl

Outputs (created):
  inference/outputs/sectors_by_iter/01-bmm-medical-technology.md
  inference/outputs/sectors_by_iter/02-bmm-pharmaceutical.md
  ...
  inference/outputs/sectors_by_iter/08-transport-engineering.md
"""

import os
import re
import json
import glob
from pathlib import Path
from collections import defaultdict, OrderedDict

# -------- Config: sectors & questions (fixed order) --------
SECTORS = [
    "Biomedical Manufacturing (Medical Technology)",
    "Biomedical Manufacturing (Pharmaceutical)",
    "Chemicals Manufacturing (Petroleum & Petrochemicals)",
    "Chemicals Manufacturing (Specialties & Other Chemicals)",
    "Electronics Manufacturing (Non-Semiconductors)",
    "Electronics Manufacturing (Semiconductors)",
    "Precision Engineering Manufacturing",
    "Transport Engineering Manufacturing",
]

QUESTION_ORDER = [
    "New Orders",
    "New Export Orders",
    "Output",
    "Stocks of Input Purchases",
    "Stocks of Finished Goods",
    "Imports",
    "Input Prices",
    "Employment",
    "Supplier Deliveries",
    "Backlogs of Orders",
    "Future Business",
]

# Map phrases in the question text -> our canonical 11 labels above
QUESTION_PATTERNS = OrderedDict([
    ("New Orders", re.compile(r"\b(New Sales Orders|New Orders)\b", re.I)),
    ("New Export Orders", re.compile(r"\b(New Export Sales|New Export Orders)\b", re.I)),
    ("Output", re.compile(r"\b(Factory Output|Output)\b", re.I)),
    ("Stocks of Input Purchases", re.compile(r"\b(Stocks of Input Purchases)\b", re.I)),
    ("Stocks of Finished Goods", re.compile(r"\b(Stocks of Finished Goods)\b", re.I)),
    ("Imports", re.compile(r"\b(Total Imports|Imports)\b", re.I)),
    ("Input Prices", re.compile(r"\b(Total Costs of Input Materials for Production|Input Prices)\b", re.I)),
    ("Employment", re.compile(r"\b(Employment Strength|Employment)\b", re.I)),
    ("Supplier Deliveries", re.compile(r"\b(Total Supplier Deliveries|Supplier Deliveries)\b", re.I)),
    ("Backlogs of Orders", re.compile(r"\b(Unfulfilled Sales Orders|Backlogs of Orders)\b", re.I)),
    ("Future Business", re.compile(r"\b(Expected Future Manufacturing Activity|Future Business)\b", re.I)),
])

# Where to look for iterations (wildcard to tolerate different model run dirs)
ITER_GLOB = "inference/outputs/*/eval_data/my_questions.jsonl/iter*.jsonl"
# Output directory
OUT_DIR = Path("inference/outputs/sectors_by_iter")


def slug_for_sector(idx: int, sector: str) -> str:
    # keep the target ordering stable with a 2-digit prefix
    base = sector.lower()
    base = re.sub(r"[()&]", "", base)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return f"{idx+1:02d}-{base}"


def extract_answer_block(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"<answer>(.*?)</answer>", text, flags=re.I | re.S)
    if m:
        return m.group(1).strip()
    return text.strip()


def detect_sector(question_text: str) -> str:
    # Exact match against the 8 sectors, prefer longest first to avoid substring accidents
    for s in SECTORS:
        if s in question_text:
            return s
    return ""


def detect_metric(question_text: str) -> str:
    for label, pat in QUESTION_PATTERNS.items():
        if pat.search(question_text):
            return label
    return ""


def read_iter_file(path: str):
    """Yield dicts parsed from jsonl."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                # Best effort: skip malformed
                continue


def gather():
    # Find all iteration files and sort by their iter number
    files = glob.glob(ITER_GLOB)
    if not files:
        print(f"No files found with pattern: {ITER_GLOB}")
        return {}, []

    # Sort by iter number (iter1, iter2, ...)
    def iter_key(p):
        m = re.search(r"iter(\d+)\.jsonl$", p)
        return int(m.group(1)) if m else 999999

    files.sort(key=iter_key)

    # data[sector][metric][iter_name] = list[answer_blocks]  (list in case multiple lines match)
    data = {s: {q: OrderedDict() for q in QUESTION_ORDER} for s in SECTORS}
    iter_names = []

    for fp in files:
        m = re.search(r"(iter\d+)\.jsonl$", fp)
        iter_name = m.group(1) if m else Path(fp).stem
        iter_names.append(iter_name)

        for rec in read_iter_file(fp):
            q = rec.get("question", "") or ""
            # common fields from your pipeline:
            # 'prediction' usually holds the final assistant text that contains <answer>...</answer>
            content = rec.get("prediction") or rec.get("answer") or ""
            # last-resort: look into messages (not recommended, but try if above missing)
            if (not content) and isinstance(rec.get("messages"), list) and rec["messages"]:
                try:
                    content = rec["messages"][-1].get("content", "")
                except Exception:
                    pass

            sector = detect_sector(q)
            metric = detect_metric(q)
            answer = extract_answer_block(content)

            if not sector or not metric or not answer:
                continue

            data[sector].setdefault(metric, OrderedDict())
            data[sector][metric].setdefault(iter_name, [])
            data[sector][metric][iter_name].append(answer)

    # de-dup iter_names preserving order
    seen = set()
    iter_names_unique = []
    for it in iter_names:
        if it not in seen:
            seen.add(it)
            iter_names_unique.append(it)

    return data, iter_names_unique


def render_sector_md(sector: str, sector_block: dict, iter_names_order: list) -> str:
    # Title & quick TOC
    lines = []
    lines.append(f"# {sector} — Answers by Iteration\n")
    lines.append("_This file collates all `<answer>...</answer>` blocks across iterations for the 11 questions, in the required order._\n")
    lines.append("## Questions\n")
    for i, q in enumerate(QUESTION_ORDER, 1):
        lines.append(f"- [{i}. {q}](#{i}-{re.sub('[^a-z0-9]+','-',q.lower()).strip('-')})")
    lines.append("")

    # Body per question
    for i, q in enumerate(QUESTION_ORDER, 1):
        anchor = f"{i}-{re.sub('[^a-z0-9]+','-',q.lower()).strip('-')}"
        lines.append(f"## {i}. {q}\n")
        # show per iteration
        have_any = False
        for iter_name in iter_names_order:
            answers = sector_block.get(q, {}).get(iter_name, [])
            if not answers:
                continue
            have_any = True
            lines.append(f"### {iter_name}\n")
            for idx, ans in enumerate(answers, 1):
                # Separate multiple matches in same iter
                if len(answers) > 1:
                    lines.append(f"**Match {idx}:**")
                lines.append(ans.strip())
                lines.append("")  # blank line
        if not have_any:
            lines.append("_No answers found for this question across iterations._\n")

    return "\n".join(lines).rstrip() + "\n"


def main():
    data, iter_names = gather()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write 8 files in the required order (prefix numbers to keep file listing ordered)
    written = 0
    for idx, sector in enumerate(SECTORS):
        sector_data = data.get(sector, {})
        # Even if empty, we still write a file so you always get 8
        md = render_sector_md(sector, sector_data, iter_names)
        fname = f"{slug_for_sector(idx, sector)}.md"
        fpath = OUT_DIR / fname
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(md)
        written += 1

    print(f"Wrote {written} sector files to: {OUT_DIR}")
    if iter_names:
        print("Iterations detected:", ", ".join(iter_names))
    else:
        print("No iteration files detected (no iter*.jsonl).")


if __name__ == "__main__":
    main()
