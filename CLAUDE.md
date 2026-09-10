# CLAUDE.md

Fork of [Alibaba-NLP/DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) (Tongyi DeepResearch),
repurposed as SIPMM's monthly economic-forecasting pipeline: it batch-runs templated research questions
asking for **Higher / No Change / Lower** verdicts (with cited URLs) to pre-estimate the **Singapore PMI**
(8 sectors × 11 indicators) and the **Logistics Growth Index (LGI)** (countries × 10 indicators) before
official release. Upstream docs are in `README.md`; this file covers the fork-specific operation.

## How inference works here (OpenRouter mode — no GPUs)

`inference/react_agent.py` was rewritten to call an OpenAI-compatible endpoint (default
`https://openrouter.ai/api/v1`) instead of upstream's local vLLM servers. `inference/run_react_infer.sh`
sources `../.env` and launches `run_multi_react.py` (thread pool, `ROLLOUT_COUNT` rollouts per question,
resume-aware). The agent runs a text-tag ReAct loop: `<tool_call>{JSON}</tool_call>` → tool executes →
result returned in `<tool_response>` tags → final answer in `<answer>` tags.

Hard limits per question: 100 LLM rounds, 150-min wall clock, 110×1024-token context cap (then one
forced-answer call), max_tokens=10000/completion.

## Model selection (critical)

**The policy model (`MODEL_PATH`) must emit the literal `<tool_call>` text tag.**
The original `alibaba/tongyi-deepresearch-30b-a3b` was delisted from OpenRouter (~Aug 2026).

- ✅ Verified working: `moonshotai/kimi-k2-0905` (current; full run ≈ $110), `anthropic/claude-sonnet-4.6`
  (~13× dearer, ≈ $5–6/task), `minimax/minimax-m2` (cheapest verified)
- ❌ Never use Qwen-family API models (`qwen/*`) as MODEL_PATH: their serving stack reserves the
  `<tool_call>` token — tags arrive mangled and no tool ever executes. `z-ai/glm-4.6` also failed testing.
- `SUMMARY_MODEL_NAME` (the `visit` page extractor — plain JSON output, no tag protocol) just needs
  cheap + fast + long-context: `google/gemini-2.5-flash` (current) beat gpt-5.5 at 1/17th the input price.

Harness hardening (commit `4870d38`, keep when merging upstream):
1. Accepts flattened (`{"name": ..., "query": ...}`) and stringified tool arguments — Sonnet drifts to
   these ~88% of the time; upstream only reads the nested `arguments` key.
2. `</tool_call>` stop sequence + truncation of anything after the first tool call — Kimi otherwise
   role-plays entire multi-turn sessions (fake tool results, premature `<answer>`) in one generation.

## Monthly cycle

1. Roll dates in the CONFIG blocks of `tools/generate_sg_survey_jsonl.py` (PMI) and/or
   `tools/lgi_question_generator.py` (LGI: `--mode individual` = country×indicator, `--mode mega` = one
   question per country), regenerate the `inference/eval_data/*.jsonl` question sets.
2. Check `.env`: `MODEL_PATH`, `SUMMARY_MODEL_NAME`, `DATASET`, `ROLLOUT_COUNT=3`, `MAX_WORKERS=3`
   (≈31 records/hr; a 264-task run ≈ 10.5 h — raise workers for speed, spend arrives faster).
   Check OpenRouter credits first: `GET /api/v1/credits` with `API_KEY`.
3. Run: `source .venv/bin/activate && bash inference/run_react_infer.sh`
   (Python 3.10 venv at `.venv/`; the script needs `python` to resolve to it).
4. Outputs land in `inference/outputs/<model-basename>_sglang/<DATASET-path>/iter{1..N}.jsonl`
   (one line per completed question: question, messages transcript, prediction, termination).
5. Export markdowns: `tools/export_sector_iteration_markdowns_v2.py` (per-sector),
   `tools/export_markdown_answers_by_sector.py` (misnamed — actually per-question),
   `tools/export_country_iteration_markdowns.py` (LGI; hardcodes an old ITER_DIR — check before use).
6. Archive: move the run dir + exports to `inference/outputs/archive/PMI/<YYYY Mon> PMI - <YYYYMMDD>/`
   (or `archive/LGI/...`). An empty live output dir usually means archived, not lost.

## Gotchas

- `.env` is read **once at launch** — editing it never affects a running process
  (verify a live run's real config via `/proc/<pid>/environ`).
- **Resume trap**: reruns skip any question whose record lacks an `"error"` field — including useless
  `"No answer found."` records. Delete bad lines from `iterN.jsonl` before restarting, or they are
  skipped forever. Credit exhaustion mid-run mass-produces exactly such records.
- Health check on a fresh run (first 2–3 records): rounds/question should be ~10–20 (1 = degenerate
  model behavior, 60+ = tool calls failing), predictions must contain verdicts + `http` URLs
  (match case-insensitively — models write "LOWER"), and `<tool_response>` bodies should show real
  Serper/Jina content, not `Invalid request format`.
- Tokenizer 404 fallback: `count_tokens` can't load a tokenizer for OpenRouter model ids and estimates
  len/4 — harmless; set `TOKENIZER_PATH` to a local HF tokenizer for accuracy.
- `inference/workspace/` is qwen_agent's runtime cache (gitignored — don't commit).
- Tool stack: search+scholar = Serper (`SERPER_KEY_ID`, `gl=sg`), visit = Jina Reader (`JINA_API_KEYS`)
  → 95K-token truncate → `SUMMARY_MODEL_NAME` extraction, PythonInterpreter = SandboxFusion
  (`SANDBOX_FUSION_ENDPOINT`, local at :8080), parse_file = local parsers (`USE_IDP=False`;
  binary-extension URLs passed to `visit` are auto-rerouted here).
- No GitHub credentials in the WSL environment: commit locally, push from the user's terminal.
