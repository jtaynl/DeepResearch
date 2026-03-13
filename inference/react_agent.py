# inference/react_agent.py
import json
import json5
import os
import time
import asyncio
import random
import datetime as dt
from typing import Dict, List, Optional, Union

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError
from transformers import AutoTokenizer

from qwen_agent.agents.fncall_agent import FnCallAgent
from qwen_agent.llm import BaseChatModel
from qwen_agent.llm.schema import Message
from qwen_agent.tools import BaseTool

from prompt import *

from tool_file import *
from tool_scholar import *
from tool_python import *
from tool_search import *
from tool_visit import *

OBS_START = '<tool_response>'
OBS_END = '\n</tool_response>'

MAX_LLM_CALL_PER_RUN = int(os.getenv('MAX_LLM_CALL_PER_RUN', '100'))

TOOL_CLASS = [FileParser(), Scholar(), Visit(), Search()]
try:
    TOOL_CLASS.append(PythonInterpreter())
except Exception:
    pass
TOOL_MAP = {tool.name: tool for tool in TOOL_CLASS}

def today_date() -> str:
    return dt.date.today().strftime("%Y-%m-%d")

def _is_binary_like_url(u: str) -> bool:
    if not isinstance(u, str):
        return False
    lower = u.lower().split('?', 1)[0]
    exts = ('.xlsx', '.xls', '.csv', '.tsv', '.pdf', '.docx', '.pptx', '.ppt',
            '.zip', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.mp3', '.wav', '.aac', '.ogg', '.flac')
    return lower.startswith(('http://', 'https://')) and any(lower.endswith(e) for e in exts)

class MultiTurnReactAgent(FnCallAgent):
    def __init__(self, function_list: Optional[List[Union[str, Dict, BaseTool]]] = None,
                 llm: Optional[Union[Dict, BaseChatModel]] = None, **kwargs):
        self.llm_generate_cfg = (llm or {}).get("generate_cfg", {}) if isinstance(llm, dict) else {}
        self.llm_local_path = (llm or {}).get("model") if isinstance(llm, dict) else None
        self.model = (llm or {}).get("model") if isinstance(llm, dict) else None

    def sanity_check_output(self, content: str) -> bool:
        return "<think>" in content and "</think>" in content

    def _openrouter_client(self) -> OpenAI:
        api_key = os.getenv("API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing API key. Set API_KEY (or OPENROUTER_API_KEY / OPENAI_API_KEY).")
        base_url = os.getenv("API_BASE", "https://openrouter.ai/api/v1")
        default_headers = {}
        http_referer = os.getenv("HTTP_REFERER") or os.getenv("OPENROUTER_HTTP_REFERER")
        x_title = os.getenv("X_TITLE") or os.getenv("OPENROUTER_X_TITLE") or os.getenv("OPENROUTER_TITLE")
        if http_referer: default_headers["HTTP-Referer"] = http_referer
        if x_title: default_headers["X-Title"] = x_title
        return OpenAI(api_key=api_key, base_url=base_url, timeout=600.0,
                      default_headers=default_headers or None)

    def call_server(self, msgs: List[Dict[str, str]], planning_port: Optional[int] = None, max_tries: int = 10) -> str:
        client = self._openrouter_client()
        base_sleep_time = 1.0
        for attempt in range(max_tries):
            try:
                print(f"--- Attempting to call OpenRouter, try {attempt + 1}/{max_tries} ---")
                r = client.chat.completions.create(
                    model=(self.model or "alibaba/tongyi-deepresearch-30b-a3b"),
                    messages=msgs,
                    stop=["\n<tool_response>", "<tool_response>"],
                    temperature=self.llm_generate_cfg.get('temperature', 0.6),
                    top_p=self.llm_generate_cfg.get('top_p', 0.95),
                    max_tokens=10000,
                    presence_penalty=self.llm_generate_cfg.get('presence_penalty', 1.1),
                )
                content = r.choices[0].message.content if r.choices else ""
                try:
                    reasoning = getattr(r.choices[0].message, "reasoning", None)
                    if isinstance(reasoning, str) and reasoning.strip():
                        content = "<think>\n" + reasoning.strip() + "\n</think>" + (content or "")
                except Exception:
                    pass
                if content and content.strip():
                    print("--- OpenRouter call successful, received a valid response ---")
                    return content.strip()
                print(f"Warning: Attempt {attempt + 1} received an empty response.")
            except (APIError, APIConnectionError, APITimeoutError) as e:
                print(f"Error: Attempt {attempt + 1} failed with an API or network error: {e}")
            except Exception as e:
                print(f"Error: Attempt {attempt + 1} failed with an unexpected error: {e}")
            if attempt < max_tries - 1:
                sleep_time = min(base_sleep_time * (2 ** attempt) + random.uniform(0, 1), 30)
                print(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
        return "OpenRouter server error!!!"

    def count_tokens(self, messages: List[Dict[str, str]]) -> int:
        try:
            tok_path = os.getenv("TOKENIZER_PATH", self.llm_local_path or "")
            if tok_path:
                tok = AutoTokenizer.from_pretrained(tok_path, trust_remote_code=True)
                full_prompt = tok.apply_chat_template(messages, tokenize=False)
                ids = tok(full_prompt, return_tensors="pt")["input_ids"]
                return int(ids.shape[-1])
        except Exception:
            pass
        text = "".join(str(m.get("content", "")) for m in messages)
        return max(1, len(text) // 4)

    def _run(self, data: Dict, model: str, **kwargs) -> Dict:
        self.model = model or (self.model or "alibaba/tongyi-deepresearch-30b-a3b")
        try:
            question = data['item']['question']
        except Exception:
            raw_msg = data['item']['messages'][1]["content"]
            question = raw_msg.split("User:")[1].strip() if "User:" in raw_msg else raw_msg

        start_time = time.time()
        planning_port = data.get('planning_port')
        answer = data['item'].get('answer', "")
        self.user_prompt = question

        system_prompt = SYSTEM_PROMPT + today_date()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

        num_llm_calls_available = MAX_LLM_CALL_PER_RUN
        round_idx = 0

        while num_llm_calls_available > 0:
            if time.time() - start_time > 150 * 60:
                return {"question": question, "answer": answer, "messages": messages,
                        "prediction": 'No answer found after 2h30mins',
                        "termination": 'No answer found after 2h30mins'}

            round_idx += 1
            num_llm_calls_available -= 1

            content = self.call_server(messages, planning_port)
            print(f'Round {round_idx}: {content}')

            if OBS_START in content:
                content = content.split(OBS_START, 1)[0]

            messages.append({"role": "assistant", "content": content.strip()})

            if '<tool_call>' in content and '</tool_call>' in content:
                block = content.split('<tool_call>')[1].split('</tool_call>')[0]
                try:
                    if "python" in block.lower():
                        try:
                            code_raw = block.split('<code>')[1].split('</code>')[0].strip()
                            result = TOOL_MAP['PythonInterpreter'].call(code_raw)
                        except Exception:
                            result = "[Python Interpreter Error]: Formatting error."
                    else:
                        payload = json5.loads(block)
                        tool_name = payload.get('name', '')
                        tool_args = payload.get('arguments', {}) or {}

                        # Smart reroute for binary URLs
                        if tool_name == "visit":
                            urls = tool_args.get("url") or tool_args.get("urls") or []
                            urls = urls if isinstance(urls, list) else [urls]
                            if any(_is_binary_like_url(u) for u in urls):
                                print("[router] Rerouting non-HTML URL(s) from visit->parse_file")
                                tool_name = "parse_file"
                                tool_args = {"files": urls}

                        result = self.custom_call_tool(tool_name, tool_args)
                except Exception:
                    result = 'Error: Tool call is not a valid JSON. Tool call must contain a valid "name" and "arguments" field.'

                messages.append({"role": "user", "content": f"{OBS_START}\n{str(result)}{OBS_END}"})

            if '<answer>' in content and '</answer>' in content:
                termination = 'answer'
                break

            if num_llm_calls_available <= 0 and '<answer>' not in content:
                messages[-1]['content'] = 'Sorry, the number of llm calls exceeds the limit.'

            max_tokens_ctx = 110 * 1024
            token_count = self.count_tokens(messages)
            print(f"round: {round_idx}, token count: {token_count}")

            if token_count > max_tokens_ctx:
                messages[-1]['content'] = (
                    "You have now reached the maximum context length you can handle. "
                    "You should stop making tool calls and, based on all the information above, "
                    "think again and provide what you consider the most likely answer in the following format:"
                    "<think>your final thinking</think>\n<answer>your answer</answer>"
                )
                content = self.call_server(messages, planning_port)
                messages.append({"role": "assistant", "content": content.strip()})
                if '<answer>' in content and '</answer>' in content:
                    prediction = messages[-1]['content'].split('<answer>')[1].split('</answer>')[0]
                    termination = 'generate an answer as token limit reached'
                else:
                    prediction = messages[-1]['content']
                    termination = 'format error: generate an answer as token limit reached'
                return {"question": question, "answer": answer, "messages": messages,
                        "prediction": prediction, "termination": termination}

        if '<answer>' in messages[-1]['content']:
            prediction = messages[-1]['content'].split('<answer>')[1].split('</answer>')[0]
            termination = 'answer'
        else:
            prediction = 'No answer found.'
            termination = 'answer not found' if num_llm_calls_available else 'exceed available llm calls'

        return {"question": question, "answer": answer, "messages": messages,
                "prediction": prediction, "termination": termination}

    def custom_call_tool(self, tool_name: str, tool_args: dict, **kwargs) -> str:
        if tool_name in TOOL_MAP:
            tool_args = dict(tool_args or {})
            tool_args["params"] = tool_args
            if "python" in tool_name.lower():
                return TOOL_MAP['PythonInterpreter'].call(tool_args)
            elif tool_name == "parse_file":
                params = {"files": tool_args.get("files", [])}
                raw = asyncio.run(TOOL_MAP[tool_name].call(params, file_root_path="./eval_data/file_corpus"))
                return raw if isinstance(raw, str) else str(raw)
            else:
                raw = TOOL_MAP[tool_name].call(tool_args, **kwargs)
                return raw if isinstance(raw, str) else str(raw)
        return f"Error: Tool {tool_name} not found"
