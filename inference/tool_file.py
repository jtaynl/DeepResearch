# inference/tool_file.py
import sys
import os
import json
import tempfile
from typing import List, Any, Tuple
import requests

from qwen_agent.tools.base import BaseTool
from qwen_agent.settings import DEFAULT_MAX_INPUT_TOKENS
from qwen_agent.utils.tokenization_qwen import count_tokens

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(current_dir))
sys.path.append('../../')

from file_tools.file_parser import SingleFileParser, compress
from file_tools.video_agent import VideoAgent

TABULAR_EXTS = {".xlsx", ".xls", ".csv", ".tsv"}
ALWAYS_INCLUDE_TABULAR_PREVIEW = os.getenv("ALWAYS_INCLUDE_TABULAR_PREVIEW", "1").lower() in ("1", "true", "yes")
TABULAR_PREVIEW_LIMIT_CHARS = int(os.getenv("TABULAR_PREVIEW_LIMIT_CHARS", "8000"))

def _is_url(path: str) -> bool:
    return isinstance(path, str) and path.lower().startswith(("http://", "https://"))

def _ext(path: str) -> str:
    base = path.split('?', 1)[0]
    return os.path.splitext(base)[1].lower()

def _looks_like_waf_html(data: bytes) -> bool:
    head = data[:4096].decode('utf-8', errors='ignore')
    return ("_Incapsula_Resource" in head) or ("incapsula" in head.lower()) or ("imperva" in head.lower())

def _is_pdf_bytes(data: bytes) -> bool:
    return data.startswith(b"%PDF-")

def _is_zip_bytes(data: bytes) -> bool:
    # XLSX are Zip containers (PK..)
    return data.startswith(b"PK\x03\x04")

def _download(url: str) -> Tuple[str, bytes]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Referer": url.split("/content/dam/", 1)[0] if "/content/dam/" in url else url,
    }
    r = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return (url, r.content)

def _save_temp(data: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path

def _xlsx_preview_with_pandas(path: str, max_sheets: int = 6, max_rows: int = 60) -> str:
    import pandas as pd
    try:
        xl = pd.ExcelFile(path)
    except Exception as e:
        return f"# Pandas could not open Excel: {e}"
    out = [f"# Detected {len(xl.sheet_names)} sheet(s): {', '.join(xl.sheet_names[:max_sheets])}"]
    for sheet in xl.sheet_names[:max_sheets]:
        try:
            df = pd.read_excel(xl, sheet_name=sheet, nrows=max_rows)
            out.append(f"# Sheet: {sheet}\n{df.to_csv(index=False)}")
        except Exception as e:
            out.append(f"# Error reading sheet '{sheet}': {e}")
    return "\n".join(out)

def _xlsx_preview_with_openpyxl(path: str, max_sheets: int = 6, max_rows: int = 60, max_cols: int = 50) -> str:
    try:
        from openpyxl import load_workbook
    except Exception as e:
        return f"# openpyxl not available: {e}"
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        return f"# openpyxl failed to open workbook: {e}"
    out = [f"# Detected {len(wb.sheetnames)} sheet(s): {', '.join(wb.sheetnames[:max_sheets])}"]
    for sheet in wb.sheetnames[:max_sheets]:
        try:
            ws = wb[sheet]
            rows_txt = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows:
                    break
                vals = ["" if v is None else str(v) for v in (row or [])[:max_cols]]
                rows_txt.append("\t".join(vals))
            out.append(f"# Sheet: {sheet}\n" + "\n".join(rows_txt))
        except Exception as e:
            out.append(f"# Error reading sheet '{sheet}': {e}")
    return "\n".join(out)

def _csv_tsv_preview(path: str, max_lines: int = 200) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)
    except Exception as e:
        return f"# Could not read text file: {e}"

def _tabular_preview(path: str) -> str:
    ext = _ext(path)
    txt = ""
    if ext in (".xlsx", ".xls"):
        try:
            import pandas  # noqa
            txt = _xlsx_preview_with_pandas(path)
        except Exception:
            txt = _xlsx_preview_with_openpyxl(path)
    elif ext in (".csv", ".tsv"):
        txt = _csv_tsv_preview(path)
    if len(txt) > TABULAR_PREVIEW_LIMIT_CHARS:
        txt = txt[:TABULAR_PREVIEW_LIMIT_CHARS] + "\n# ... [truncated]"
    return txt

async def file_parser(params, **kwargs):
    """Accepts local paths or URLs; downloads URLs; validates magic bytes; falls back to HTML when 'PDF' isn't a real PDF."""
    inputs = params.get('files', [])
    if isinstance(inputs, str):
        inputs = [inputs]

    resolved_paths: List[str] = []
    errors: List[str] = []

    for item in inputs:
        try:
            if _is_url(item):
                url, data = _download(item)

                ext = _ext(item)
                # WAF detection for EDB/Imperva
                if _looks_like_waf_html(data):
                    errors.append(f"# WAF/Incapsula blocked direct download from {url}. "
                                  f"Please upload the file locally (eval_data/file_corpus) or provide an accessible mirror.")
                    continue

                # Validate by magic bytes and fix-up type if needed
                if ext in (".xlsx", ".xls"):
                    if not _is_zip_bytes(data):
                        errors.append(f"# {url} did not return a real Excel (no ZIP header). It might be a guard page.")
                        continue
                    path = _save_temp(data, ext or ".xlsx")
                    resolved_paths.append(path)

                elif ext == ".pdf":
                    if _is_pdf_bytes(data):
                        path = _save_temp(data, ".pdf")
                        resolved_paths.append(path)
                    else:
                        # treat as HTML/text instead of exploding
                        path = _save_temp(data, ".html")
                        resolved_paths.append(path)

                else:
                    # generic save
                    path = _save_temp(data, ext or ".bin")
                    resolved_paths.append(path)
            else:
                abs_path = os.path.abspath(item)
                if os.path.exists(abs_path):
                    resolved_paths.append(abs_path)
                else:
                    errors.append(f"# Warning: Local path not found: {item}")
        except Exception as e:
            errors.append(f"# Error resolving {item}: {e}")

    results: List[str] = []
    file_results: List[str] = []

    for local_path in resolved_paths:
        try:
            result = SingleFileParser().call(json.dumps({'url': local_path}), **kwargs) or ""
            # Always append a tabular preview for spreadsheets/CSV/TSV
            if ALWAYS_INCLUDE_TABULAR_PREVIEW and _ext(local_path) in TABULAR_EXTS:
                preview = _tabular_preview(local_path)
                if preview:
                    result += ("\n\n# Tabular preview (local):\n" + preview)
            results.append(f"# File: {os.path.basename(local_path)}\n{result}")
            file_results.append(result)
        except Exception as e:
            fb_txt = ""
            if _ext(local_path) in TABULAR_EXTS:
                fb_txt = "\n# Tabular preview (local):\n" + _tabular_preview(local_path)
            results.append(f"# Error processing {os.path.basename(local_path)}: {str(e)}{fb_txt}")

    results.extend(errors)

    if count_tokens(json.dumps(results)) < DEFAULT_MAX_INPUT_TOKENS:
        return results
    else:
        return compress(file_results)

class FileParser(BaseTool):
    name = "parse_file"
    description = "Parse local or remote files (PDF, DOCX, PPTX, TXT, CSV, XLSX, etc.). Accepts URLs or local paths."
    parameters = [
        {
            'name': 'files',
            'type': 'array',
            'array_type': 'string',
            'description': 'File paths or URLs to parse.',
            'required': True
        }
    ]

    async def call(self, params, file_root_path):
        inputs = params.get("files", [])
        if isinstance(inputs, str):
            inputs = [inputs]

        local_candidates: List[str] = []
        remote_or_abs: List[str] = []

        for f_name in inputs:
            if _is_url(f_name):
                remote_or_abs.append(f_name)
            else:
                if os.path.isabs(f_name):
                    remote_or_abs.append(f_name)
                else:
                    local_candidates.append(os.path.join(file_root_path, f_name))

        outputs: List[Any] = []

        if local_candidates:
            try:
                resp = await file_parser({'files': local_candidates})
                resp = resp[:30000]
                parsed = ' '.join(resp)
                outputs.extend([f'File token number: {len(parsed.split())}\nFile content:\n'] + resp)
            except Exception as e:
                outputs.append(f"# Error parsing local corpus files: {e}")

        if remote_or_abs:
            try:
                resp = await file_parser({'files': remote_or_abs})
                resp = resp[:30000]
                parsed = ' '.join(resp)
                outputs.extend([f'File token number: {len(parsed.split())}\nFile content:\n'] + resp)
            except Exception as e:
                outputs.append(f"# Error parsing remote/absolute files: {e}")

        return outputs
