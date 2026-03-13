# tools/export_markdown_answers_per_question.py
import os, re, json, glob, pathlib, datetime
from collections import defaultdict

# ---- Config ----
INPUT_Q_PATH = "inference/eval_data/my_questions.jsonl"
OUTPUT_GLOB = "inference/outputs/*/eval_data/my_questions.jsonl/iter*.jsonl"
OUT_DIR = "inference/outputs/questions"

# Extract the contents inside <answer>...</answer>
ANS_TAG = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)

# ---------- helpers ----------
def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"['’]", "", s)                 # drop quotes/apostrophes
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "q"

def sanitize_filename(s: str) -> str:
    s = s.replace("/", "-").replace("&", "and")
    s = re.sub(r"[^a-zA-Z0-9\-\._\(\) ]+", "", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s

def read_questions_in_order(path):
    """Return a list of question strings in the order they appear in the input jsonl."""
    order = []
    if not os.path.exists(path):
        return order
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            q = obj.get("question", "")
            if q:
                order.append(q)
    return order

def extract_answer(obj) -> str:
    """Prefer obj['prediction']; else find <answer>…</answer> anywhere in messages."""
    pred = obj.get("prediction", "")
    if isinstance(pred, str) and pred.strip():
        return pred.strip()
    # fallback: search messages (scan from the end)
    msgs = obj.get("messages")
    if isinstance(msgs, list):
        for m in reversed(msgs):
            content = m.get("content", "") if isinstance(m, dict) else ""
            if not isinstance(content, str):
                continue
            m_ = ANS_TAG.search(content)
            if m_:
                return m_.group(1).strip()
    return ""

def load_iter_file(path):
    """
    Yields dicts: {
      'question': str,
      'answer_md': str,
      'iter_num': int,
      'run_name': str,  # parent dir under inference/outputs
      'src_path': str
    }
    """
    # iter number
    it_m = re.search(r"iter(\d+)\.jsonl$", path)
    iter_num = int(it_m.group(1)) if it_m else 0
    # run directory name
    # e.g. inference/outputs/<RUN>/eval_data/my_questions.jsonl/iterX.jsonl
    parts = pathlib.Path(path).as_posix().split("/")
    run_name = parts[2] if len(parts) >= 3 and parts[0] == "inference" and parts[1] == "outputs" else "run"

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            q = obj.get("question", "")
            if not q:
                continue
            a = extract_answer(obj)
            if not a:
                # skip empty answers (we only archive actual <answer> content)
                continue
            yield {
                "question": q,
                "answer_md": a,
                "iter_num": iter_num,
                "run_name": run_name,
                "src_path": path
            }

def write_question_file(q_idx, question, entries):
    """
    Write a single markdown file for one question containing all iterations (latest first).
    """
    os.makedirs(OUT_DIR, exist_ok=True)

    # sort by (run_name, iter_num desc) or just iter desc across runs — we’ll do iter desc then run_name
    entries_sorted = sorted(entries, key=lambda d: (-d["iter_num"], d["run_name"].lower()))

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append(f"# Q{q_idx:03d} — Research Answer (All Iterations)")
    lines.append("")
    lines.append(f"_Generated on {ts}_")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(question.strip())
    lines.append("")

    # If no answers, still produce the file with a note.
    if not entries_sorted:
        lines.append("> No <answer> content found across iterations.")
    else:
        # TOC
        lines.append("## Iterations")
        for e in entries_sorted:
            lines.append(f"- [iter {e['iter_num']} — {e['run_name']}](#iter-{e['iter_num']}-{slugify(e['run_name'])})")
        lines.append("")

        # Sections for each iteration
        latest_iter = entries_sorted[0]["iter_num"]
        for e in entries_sorted:
            tag = " *(latest)*" if e["iter_num"] == latest_iter else ""
            anchor = f"iter-{e['iter_num']}-{slugify(e['run_name'])}"
            lines.append(f"### {anchor.replace('-', ' ').title()}{tag}")
            lines.append("")
            lines.append(f"**Source:** `{e['run_name']}`  |  **iter:** `{e['iter_num']}`")
            lines.append("")
            lines.append(e["answer_md"])
            lines.append("")

    # filename: keep stable numeric prefix + short slug of question
    short = question[:80]
    fname = f"Q{q_idx:03d}_{sanitize_filename(short)}.md"
    out_path = os.path.join(OUT_DIR, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Load canonical question order (so file numbers are stable)
    question_order = read_questions_in_order(INPUT_Q_PATH)
    # Fallback: if missing, we’ll build order from discovered outputs
    known_questions = list(question_order)

    # Collect all answers across runs & iters
    answers_map = defaultdict(list)  # question -> list[entries]
    iter_files = sorted(glob.glob(OUTPUT_GLOB))
    for p in iter_files:
        for rec in load_iter_file(p):
            answers_map[rec["question"]].append(rec)
            if rec["question"] not in known_questions:
                known_questions.append(rec["question"])

    # Write per-question files
    written = []
    for idx, q in enumerate(known_questions, start=1):
        outp = write_question_file(idx, q, answers_map.get(q, []))
        written.append((idx, q, outp))

    # Build index
    idx_lines = ["# SG Survey — Answers Per Question (All Iterations)", ""]
    if not written:
        idx_lines.append("_No questions found; nothing written._")
    else:
        for idx, q, path in written:
            rel = os.path.basename(path)
            idx_lines.append(f"- **Q{idx:03d}** — [{rel}]({rel})")
    with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx_lines))

    print(f"Discovered {len(iter_files)} iter file(s).")
    print(f"Wrote {len(written)} Markdown files to: {OUT_DIR}")
    print(f"Index: {os.path.join(OUT_DIR, 'INDEX.md')}")

if __name__ == "__main__":
    main()
