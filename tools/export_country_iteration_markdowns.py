#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Export country-level Markdown files, grouping all iterations' <answer> blocks
for each of the 10 questions in the specified order.

Inputs (defaults can be edited below):
- Questions JSONL path:
    inference/eval_data/my_questions.jsonl
- Iteration outputs directory (auto-discovers iter*.jsonl):
    inference/outputs/tongyi-deepresearch-30b-a3b_sglang/eval_data/my_questions.jsonl/

Outputs:
- One Markdown file per country (8 total), in:
    inference/outputs/country
- An INDEX.md with quick links.

Assumes each JSONL line has at least:
{
  "question": "...",
  "messages": [...],
  "prediction": "<answer> ... </answer>"    # often present
}
We’ll try, in order: prediction, last assistant message, or any content containing <answer>...</answer>.

Author: ChatGPT
"""

import os
import re
import json
import glob
from collections import defaultdict
from datetime import datetime

# -------------------------------------------------------------------
# CONFIG (edit if your paths differ)
# -------------------------------------------------------------------
QUESTIONS_PATH = "inference/eval_data/my_questions.jsonl"
ITER_DIR = "inference/outputs/tongyi-deepresearch-30b-a3b_sglang/eval_data/my_questions.jsonl"
OUT_DIR = "inference/outputs/country"

# Countries (order fixed)
COUNTRY_ORDER = [
    "Singapore",
    "China",
    "India",
    "Japan",
    "Australia",
    "South Korea",
    "Indonesia",
    "Saudi Arabia",
]

# Questions (order fixed)
QUESTION_ORDER = [
    "Business Volume",
    "Business Sentiment",
    "Transportation",
    "Transport Capacity",
    "Employment",
    "Logistics Costs",
    "Warehousing",
    "Warehouse Capacity",
    "Inventory",
    "Goods for Sale",
]

# Regex to capture <answer>…</answer>
ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                # Ignore malformed lines
                continue

def normalize_quote_variants(text: str) -> str:
    # Handle curly apostrophes & misc Unicode variants
    return text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")

def detect_country(question: str) -> str | None:
    qn = normalize_quote_variants(question).lower()
    for c in COUNTRY_ORDER:
        tokens = {c, f"{c}'s"}  # match both "Singapore" and "Singapore's"
        if any(tok.lower() in qn for tok in tokens):
            return c
    return None

def detect_question_topic(question: str) -> str | None:
    qn = normalize_quote_variants(question).lower()
    for topic in QUESTION_ORDER:
        if topic.lower() in qn:
            return topic
    return None

def extract_answer_from_item(item: dict) -> str | None:
    """
    Try, in order:
      1) item["prediction"] (common place for final answer)
      2) last assistant message content
      3) any string field containing an <answer>…</answer> block
    Return the inner markdown (without <answer> tags), trimmed.
    """
    candidates: list[str] = []

    # 1) prediction
    pred = item.get("prediction")
    if isinstance(pred, str) and pred.strip():
        candidates.append(pred)

    # 2) scan messages for the last assistant content
    msgs = item.get("messages")
    if isinstance(msgs, list) and msgs:
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant":
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    candidates.append(c)
                    break

    # 3) fall back to any string field in the object that contains <answer>
    if not candidates:
        for v in item.values():
            if isinstance(v, str) and "<answer>" in v:
                candidates.append(v)

    # Extract the last <answer>...</answer> block among candidates
    for cand in candidates:
        matches = ANSWER_RE.findall(cand or "")
        if matches:
            return matches[-1].strip()

    return None

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def safe_filename(name: str) -> str:
    bad = r'<>:"/\|?*'
    out = "".join("_" if ch in bad else ch for ch in name)
    return out.strip().replace("  ", " ")

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    ensure_dir(OUT_DIR)

    # Discover iter*.jsonl files (iter1, iter2, iter3, …)
    iter_files = sorted(glob.glob(os.path.join(ITER_DIR, "iter*.jsonl")))
    if not iter_files:
        print(f"No iteration files found in: {ITER_DIR}")
        return

    # Build a lookup: (country, topic) -> { iter_name: answer_md }
    answers: dict[tuple, dict[str, str]] = defaultdict(dict)

    # Also track question string per (country, topic) for reference
    questions_seen: dict[tuple, str] = {}

    # Parse each iteration file
    for iter_path in iter_files:
        iter_name = os.path.splitext(os.path.basename(iter_path))[0]  # iter1
        for item in read_jsonl(iter_path):
            q = item.get("question", "")
            if not q:
                continue

            country = detect_country(q or "")
            topic = detect_question_topic(q or "")

            if not country or not topic:
                # Not a recognized (country, topic) row; skip
                continue

            ans_md = extract_answer_from_item(item)
            if not ans_md:
                continue

            key = (country, topic)
            # Save the first question variant seen (for context header/links)
            questions_seen.setdefault(key, q)
            answers[key][iter_name] = ans_md

    # Write one file per country
    written = 0
    for country in COUNTRY_ORDER:
        # Build markdown
        lines = []
        lines.append(f"# {country} — Survey Answers by Iteration")
        lines.append("")
        lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
        lines.append("")
        lines.append("> This document consolidates answers extracted from all iterations for the 10 questions, in the fixed order.")
        lines.append("")

        has_any = False

        for topic in QUESTION_ORDER:
            key = (country, topic)
            iter_map = answers.get(key, {})

            lines.append(f"## {topic}")
            # Optional: show question text (first seen)
            q_text = questions_seen.get(key)
            if q_text:
                lines.append("")
                lines.append("<details>")
                lines.append("<summary>Original question</summary>")
                lines.append("")
                lines.append(q_text.strip())
                lines.append("")
                lines.append("</details>")
                lines.append("")

            # List iterations in numeric order (iter1, iter2, ...)
            its_sorted = sorted(iter_map.keys(), key=lambda s: (len(s), s))
            if not its_sorted:
                lines.append("_No answer found across iterations._")
                lines.append("")
                continue

            has_any = True
            for it in its_sorted:
                lines.append(f"### {it}")
                lines.append("")
                lines.append(iter_map[it])
                lines.append("")

        # Write only if at least one section had answers (still write empty for consistency)
        fname = f"{COUNTRY_ORDER.index(country)+1:02d} - {safe_filename(country)}.md"
        fpath = os.path.join(OUT_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        written += 1

    # Create a simple index
    idx_lines = [
        "# Country Answer Bundles (All Iterations)",
        "",
        f"_Output directory_: `{OUT_DIR}`",
        "",
        "## Files",
        "",
    ]
    for country in COUNTRY_ORDER:
        fname = f"{COUNTRY_ORDER.index(country)+1:02d} - {safe_filename(country)}.md"
        idx_lines.append(f"- [{country}]({fname})")

    with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx_lines))

    print(f"Wrote {written} country files to: {OUT_DIR}")
    print(f"Index: {os.path.join(OUT_DIR, 'INDEX.md')}")


if __name__ == "__main__":
    main()
