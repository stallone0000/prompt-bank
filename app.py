#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict
from urllib import error, request
from urllib.parse import urlparse


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATA_PATH = APP_DIR / "data" / "demo_examples.json"

PROMPT_DIRECT = """You are a helpful and harmless assistant.
Let's think step by step:
{PROBLEM}"""

PROMPT_SHORT = """You are a helpful and harmless assistant.
You may be given an optional Solving Hints section. Use it only if it is relevant to the problem; otherwise ignore it completely.
[Solving Hints]
{SOLVING_HINTS}
[/Solving Hints]
Let's think step by step and use less than 200 tokens:
{PROBLEM}"""

PROMPT_COD = """You are a helpful and harmless assistant.
You may be given an optional Solving Hints section. Use it only if it is relevant to the problem; otherwise ignore it completely.
[Solving Hints]
{SOLVING_HINTS}
[/Solving Hints]
Think step by step, but only keep a minimum draft for each thinking step, with 5 words at most. Problem:
{PROBLEM}"""

PROMPT_TRYTO = """You are a helpful and harmless assistant.
You may be given an optional Solving Hints section. Use it only if it is relevant to the problem; otherwise ignore it completely.
[Solving Hints]
{SOLVING_HINTS}
[/Solving Hints]
If you use the solving hints, please try to reduce the number of tokens used. Problem:
{PROBLEM}"""

TOKEN_USAGE_FIELDS = [
    "usage.prompt_tokens",
    "usage.completion_tokens",
    "usage.total_tokens",
]
VERIFY_PROMPT_TEMPLATE = """
You are a answer checker.

Given:
1. A problem.
2. The official correct answer.
3. A candidate model answer (which may contain explanations).

Task:
- Check whether the candidate's FINAL answer matches the official answer.
- Ignore differences in explanation style.
- If they match, respond with exactly one word: CORRECT
- If they do not match, respond with exactly one word: INCORRECT

Problem:
{question}

Official answer:
{official_answer}

Candidate model answer:
{candidate_answer}
""".strip()


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    company: str
    label: str
    api_model: str
    prompt_template: str
    input_price_yuan_per_million: float | None
    output_price_yuan_per_million: float | None
    supports_reasoning_trace: bool
    max_tokens: int = 32000


MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "doubao": ModelConfig(
        model_id="doubao",
        company="ByteDance / Doubao",
        label="Doubao Seed 1.8",
        api_model="volcengine/doubao-seed-1-8",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=2.0,
        supports_reasoning_trace=True,
    ),
    "doubao2pro": ModelConfig(
        model_id="doubao2pro",
        company="ByteDance / Doubao",
        label="Doubao Seed 2.0 Pro",
        api_model="volcengine/doubao-seed-2-0-pro",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=3.2,
        output_price_yuan_per_million=16.0,
        supports_reasoning_trace=True,
    ),
    "oss": ModelConfig(
        model_id="oss",
        company="Qiniu / GPT-OSS",
        label="GPT-OSS-120B",
        api_model="qiniu/gpt-oss-120b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=1.08,
        output_price_yuan_per_million=5.4,
        supports_reasoning_trace=False,
    ),
    "oss20": ModelConfig(
        model_id="oss20",
        company="Qiniu / GPT-OSS",
        label="GPT-OSS-20B",
        api_model="qiniu/gpt-oss-20b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=0.72,
        output_price_yuan_per_million=3.6,
        supports_reasoning_trace=True,
    ),
    "gemini": ModelConfig(
        model_id="gemini",
        company="Google / Gemini",
        label="Gemini 3 Flash",
        api_model="cloudsway/gemini-3-flash-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=2.52,
        output_price_yuan_per_million=15.12,
        supports_reasoning_trace=False,
    ),
    "qwen35plus": ModelConfig(
        model_id="qwen35plus",
        company="Alibaba / Qwen",
        label="Qwen 3.5 Plus",
        api_model="alibaba/qwen3.5-plus",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=4.8,
        supports_reasoning_trace=True,
    ),
    "qwen35flash": ModelConfig(
        model_id="qwen35flash",
        company="Alibaba / Qwen",
        label="Qwen 3.5 Flash",
        api_model="alibaba/qwen3.5-flash",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.2,
        output_price_yuan_per_million=2.0,
        supports_reasoning_trace=True,
    ),
    "qwen36plus": ModelConfig(
        model_id="qwen36plus",
        company="Alibaba / Qwen",
        label="Qwen 3.6 Plus",
        api_model="qwen/qwen3.6-plus",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.0,
        output_price_yuan_per_million=12.0,
        supports_reasoning_trace=True,
    ),
    "glm5": ModelConfig(
        model_id="glm5",
        company="Z.AI / GLM",
        label="GLM-5",
        api_model="z-ai/glm-5",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.8,
        output_price_yuan_per_million=12.6,
        supports_reasoning_trace=True,
    ),
    "glm51": ModelConfig(
        model_id="glm51",
        company="Z.AI / GLM",
        label="GLM-5.1",
        api_model="z-ai/glm-5.1",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=6.0,
        output_price_yuan_per_million=24.0,
        supports_reasoning_trace=True,
    ),
    "minimax25hs": ModelConfig(
        model_id="minimax25hs",
        company="MiniMax",
        label="MiniMax M2.5 Highspeed",
        api_model="minimax/MiniMax-M2.5-highspeed",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=4.2,
        output_price_yuan_per_million=16.8,
        supports_reasoning_trace=True,
    ),
    "minimax27hs": ModelConfig(
        model_id="minimax27hs",
        company="MiniMax",
        label="MiniMax M2.7 Highspeed",
        api_model="minimax/MiniMax-M2.7-highspeed",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=4.2,
        output_price_yuan_per_million=16.8,
        supports_reasoning_trace=True,
    ),
    "kimi25": ModelConfig(
        model_id="kimi25",
        company="Moonshot / Kimi",
        label="Kimi K2.5",
        api_model="qiniu/kimi-k2.5",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.8,
        output_price_yuan_per_million=14.7,
        supports_reasoning_trace=True,
    ),
}


def load_examples_payload() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing demo data file at {DATA_PATH}. Run `python scripts/build_demo_examples.py` first."
        )
    with DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    payload["models"] = {
        model_id: {
            **payload.get("models", {}).get(model_id, {}),
            "company": config.company,
            "label": config.label,
            "apiModel": config.api_model,
            "supportsReasoningTrace": config.supports_reasoning_trace,
            "showsReasoningTrace": config.supports_reasoning_trace,
            "maxTokens": config.max_tokens,
            "paperPricing": {
                "inputYuanPerMillion": config.input_price_yuan_per_million,
                "outputYuanPerMillion": config.output_price_yuan_per_million,
            },
        }
        for model_id, config in MODEL_CONFIGS.items()
    }
    payload["selectionRule"] = "Curated from rebuttal runs whose original direct CoT was very long (>6000) and shrank substantially under TRS."
    payload["tokenUsageFields"] = TOKEN_USAGE_FIELDS
    payload["verifier"] = {
        "model": get_verify_model(),
        "promptStyle": "Original DeepMath answer-checker prompt",
    }
    return payload


def compute_cost_yuan(prompt_tokens: int, completion_tokens: int, config: ModelConfig) -> float:
    return (
        prompt_tokens / 1_000_000 * config.input_price_yuan_per_million
        + completion_tokens / 1_000_000 * config.output_price_yuan_per_million
    )


def build_prompt(template: str, question: str, skill_text: str) -> str:
    return template.replace("{SOLVING_HINTS}", skill_text).replace("{PROBLEM}", question)


def build_direct_prompt(question: str) -> str:
    return PROMPT_DIRECT.replace("{PROBLEM}", question)


def get_api_key() -> str:
    return os.environ.get("TRS_DEMO_API_KEY") or os.environ.get("REBUTTAL_API_KEY", "")


def get_verify_model() -> str:
    return os.environ.get("TRS_DEMO_VERIFY_MODEL", "openai/gpt-5-mini").strip() or "openai/gpt-5-mini"


def build_opener() -> request.OpenerDirector:
    proxy_url = os.environ.get("TRS_DEMO_PROXY_URL", "").strip()
    if not proxy_url:
        return request.build_opener()
    return request.build_opener(
        request.ProxyHandler(
            {
                "http": proxy_url,
                "https": proxy_url,
            }
        )
    )


def build_api_payload(prompt_text: str, config: ModelConfig, stream: bool) -> Dict[str, Any]:
    return {
        "model": config.api_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "content_filter": False,
        "stream": stream,
        "temperature": float(os.environ.get("TRS_DEMO_TEMPERATURE", "0.7")),
        "max_tokens": config.max_tokens,
        "top_p": 0.9,
        "top_k": 0,
        "repetition_penalty": 1.05,
        "num_beams": 1,
        "user": "trs_demo_web",
    }


def build_json_api_request(payload: Dict[str, Any]) -> request.Request:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Missing TRS_DEMO_API_KEY (or REBUTTAL_API_KEY) in the server environment.")

    api_url = os.environ.get("TRS_DEMO_API_URL", "http://api.360.cn/v1/chat/completions").strip()
    body = json.dumps(payload).encode("utf-8")
    return request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Host": "api.360.cn",
        },
        method="POST",
    )


def make_api_request(prompt_text: str, config: ModelConfig, stream: bool) -> request.Request:
    return build_json_api_request(build_api_payload(prompt_text, config, stream))


def parse_usage_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_verifier_verdict(content: str) -> str:
    first_line = content.splitlines()[0].strip().upper() if content else ""
    if "INCORRECT" in first_line:
        return "INCORRECT"
    if "CORRECT" in first_line:
        return "CORRECT"
    return first_line or "UNKNOWN"


def get_max_retries() -> int:
    try:
        return max(1, int(os.environ.get("TRS_DEMO_MAX_RETRIES", "5")))
    except ValueError:
        return 5


def get_timeout_seconds() -> int:
    try:
        return max(1, int(os.environ.get("TRS_DEMO_TIMEOUT_SECONDS", "300")))
    except ValueError:
        return 300


def retry_sleep_seconds(attempt_number: int) -> float:
    return min(2.0, 0.35 * attempt_number)


def format_upstream_error(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        detail = exc.read().decode("utf-8", errors="replace")
        return f"HTTP {exc.code}: {detail}"
    return str(exc)


def verify_answer(question_text: str, reference_answer: str, candidate_answer: str) -> Dict[str, Any]:
    verifier_model = get_verify_model()
    cleaned_candidate = (candidate_answer or "").strip()
    max_retries = get_max_retries()
    if not cleaned_candidate:
        return {
            "status": "missing",
            "label": "No Final Answer",
            "reference_answer": reference_answer,
            "verifier_model": verifier_model,
            "verdict": "MISSING",
            "verifier_response": "",
        }

    verify_prompt = VERIFY_PROMPT_TEMPLATE.format(
        question=question_text,
        official_answer=reference_answer,
        candidate_answer=cleaned_candidate,
    )
    payload = {
        "model": verifier_model,
        "messages": [{"role": "user", "content": verify_prompt}],
        "content_filter": False,
        "stream": False,
    }

    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            with opener.open(build_json_api_request(payload), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries:
                return {
                    "status": "unknown",
                    "label": "Verifier Error",
                    "reference_answer": reference_answer,
                    "verifier_model": verifier_model,
                    "verdict": "UNKNOWN",
                    "verifier_response": last_error,
                }
            time.sleep(retry_sleep_seconds(attempt))

    if parsed is None:
        return {
            "status": "unknown",
            "label": "Verifier Error",
            "reference_answer": reference_answer,
            "verifier_model": verifier_model,
            "verdict": "UNKNOWN",
            "verifier_response": last_error,
        }

    choices = parsed.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    content = message.get("content", "").strip()
    verdict = parse_verifier_verdict(content)
    if verdict == "CORRECT":
        status = "correct"
        label = "Correct"
    elif verdict == "INCORRECT":
        status = "incorrect"
        label = "Incorrect"
    else:
        status = "unknown"
        label = "Verifier Unclear"

    return {
        "status": status,
        "label": label,
        "reference_answer": reference_answer,
        "verifier_model": verifier_model,
        "verdict": verdict,
        "verifier_response": content,
    }


def build_result(
    question_text: str,
    config: ModelConfig,
    reasoning_text: str,
    answer_text: str,
    usage: Dict[str, Any],
    reference_answer: str,
) -> Dict[str, Any]:
    prompt_tokens = parse_usage_int(usage.get("prompt_tokens"))
    completion_tokens = parse_usage_int(usage.get("completion_tokens"))
    total_tokens = parse_usage_int(usage.get("total_tokens"))
    cost_yuan = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_yuan = round(compute_cost_yuan(prompt_tokens, completion_tokens, config), 6)

    correctness = verify_answer(question_text, reference_answer, answer_text)

    return {
        "reasoning_text": reasoning_text or "",
        "answer_text": answer_text or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_yuan": cost_yuan,
        "correctness": correctness,
    }


def extract_reasoning_text(message: Dict[str, Any]) -> str:
    return message.get("reasoning_content", "") or ""


def extract_answer_text(message: Dict[str, Any]) -> str:
    return message.get("content", "") or ""


def compute_live_summary(direct: Dict[str, Any], trs: Dict[str, Any]) -> Dict[str, Any]:
    completion_saved = None
    if direct["completion_tokens"] is not None and trs["completion_tokens"] is not None:
        completion_saved = direct["completion_tokens"] - trs["completion_tokens"]

    total_saved = None
    if direct["total_tokens"] is not None and trs["total_tokens"] is not None:
        total_saved = direct["total_tokens"] - trs["total_tokens"]

    cost_saved = None
    if direct["cost_yuan"] is not None and trs["cost_yuan"] is not None:
        cost_saved = round(direct["cost_yuan"] - trs["cost_yuan"], 6)

    completion_reduction_pct = None
    if completion_saved is not None and direct["completion_tokens"] and direct["completion_tokens"] > 0:
        completion_reduction_pct = round(completion_saved / direct["completion_tokens"] * 100, 2)
    return {
        "completion_tokens_saved": completion_saved,
        "completion_reduction_pct": completion_reduction_pct,
        "total_tokens_saved": total_saved,
        "cost_saved_yuan": cost_saved,
    }


def model_payload(config: ModelConfig) -> Dict[str, Any]:
    return {
        "id": config.model_id,
        "company": config.company,
        "label": config.label,
        "apiModel": config.api_model,
        "supportsReasoningTrace": config.supports_reasoning_trace,
        "showsReasoningTrace": config.supports_reasoning_trace,
        "maxTokens": config.max_tokens,
        "paperPricing": {
            "inputYuanPerMillion": config.input_price_yuan_per_million,
            "outputYuanPerMillion": config.output_price_yuan_per_million,
        },
    }


def call_model(question_text: str, prompt_text: str, config: ModelConfig, reference_answer: str) -> Dict[str, Any]:
    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    max_retries = get_max_retries()
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            with opener.open(make_api_request(prompt_text, config, stream=False), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries:
                raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}") from exc
            time.sleep(retry_sleep_seconds(attempt))

    if parsed is None:
        raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}")

    choices = parsed.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    usage = parsed.get("usage", {}) or {}
    return build_result(
        question_text=question_text,
        config=config,
        reasoning_text=extract_reasoning_text(message),
        answer_text=extract_answer_text(message),
        usage=usage,
        reference_answer=reference_answer,
    )


def stream_model(
    question_text: str,
    prompt_text: str,
    config: ModelConfig,
    reference_answer: str,
    on_delta: Callable[[str, str], None],
    on_retry: Callable[[int, int, str], None],
) -> Dict[str, Any]:
    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    max_retries = get_max_retries()
    last_error = ""

    for attempt in range(1, max_retries + 1):
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        usage: Dict[str, Any] = {}

        try:
            with opener.open(make_api_request(prompt_text, config, stream=True), timeout=timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:]
                    if data.startswith(" "):
                        data = data[1:]
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    choices = chunk.get("choices", [])
                    delta = choices[0].get("delta", {}) if choices else {}
                    reasoning_piece = extract_reasoning_text(delta)
                    answer_piece = extract_answer_text(delta)
                    if reasoning_piece:
                        reasoning_parts.append(reasoning_piece)
                        on_delta("reasoning", reasoning_piece)
                    if answer_piece:
                        answer_parts.append(answer_piece)
                        on_delta("answer", answer_piece)

            return build_result(
                question_text=question_text,
                config=config,
                reasoning_text="".join(reasoning_parts),
                answer_text="".join(answer_parts),
                usage=usage,
                reference_answer=reference_answer,
            )
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries:
                raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}") from exc
            on_retry(attempt + 1, max_retries, last_error)
            time.sleep(retry_sleep_seconds(attempt))

    raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}")


def serialize_live_comparison(example: Dict[str, Any], config: ModelConfig) -> Dict[str, Any]:
    question = example["question"]
    reference_answer = example["answer"]
    skill_text = example["archived"][config.model_id]["trs"]["skill_text"]
    direct_prompt = build_direct_prompt(question)
    trs_prompt = build_prompt(config.prompt_template, question, skill_text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_direct = pool.submit(call_model, question, direct_prompt, config, reference_answer)
        future_trs = pool.submit(call_model, question, trs_prompt, config, reference_answer)
        direct = future_direct.result()
        trs = future_trs.result()

    return {
        "model": model_payload(config),
        "direct": direct,
        "trs": {
            **trs,
            "skill_text": skill_text,
            "skill_score": example["archived"][config.model_id]["trs"]["skill_score"],
        },
        "summary": compute_live_summary(direct, trs),
    }


class DemoHandler(SimpleHTTPRequestHandler):
    server_version = "TRSDemo/0.2"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args))

    def _send_json(self, payload: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _send_sse_event(self, event: str, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        message = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
        self.wfile.write(message)
        self.wfile.flush()

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        return json.loads(body or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/examples":
            self._send_json(self.server.examples_payload)
            return

        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def _resolve_request(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], ModelConfig]:
        example_id = payload.get("exampleId", "")
        model_id = payload.get("modelId", "")

        if model_id not in MODEL_CONFIGS:
            raise ValueError(f"Unsupported modelId: {model_id}")

        example = self.server.examples_by_id.get(example_id)
        if not example:
            raise ValueError(f"Unknown exampleId: {example_id}")

        return example, MODEL_CONFIGS[model_id]

    def _handle_stream_run(self, example: Dict[str, Any], config: ModelConfig) -> None:
        question = example["question"]
        reference_answer = example["answer"]
        archived = example["archived"][config.model_id]
        skill_text = archived["trs"]["skill_text"]
        prompts = {
            "direct": build_direct_prompt(question),
            "trs": build_prompt(config.prompt_template, question, skill_text),
        }

        self._send_sse_headers()
        self._send_sse_event(
            "meta",
            {
                "exampleId": example["id"],
                "model": model_payload(config),
                "referenceAnswer": reference_answer,
            },
        )

        events: queue.Queue[tuple[str, Dict[str, Any]]] = queue.Queue()
        results: Dict[str, Dict[str, Any]] = {}
        failures: list[str] = []

        def emit(event_name: str, payload: Dict[str, Any]) -> None:
            events.put((event_name, payload))

        def runner(lane: str) -> None:
            try:
                emit("lane_status", {"lane": lane, "status": "started"})
                result = stream_model(
                    question_text=question,
                    prompt_text=prompts[lane],
                    config=config,
                    reference_answer=reference_answer,
                    on_delta=lambda kind, text: emit("lane_delta", {"lane": lane, "kind": kind, "text": text}),
                    on_retry=lambda attempt, max_attempts, error_message: emit(
                        "lane_retry",
                        {
                            "lane": lane,
                            "attempt": attempt,
                            "maxAttempts": max_attempts,
                            "error": error_message,
                        },
                    ),
                )
                if lane == "trs":
                    result["skill_text"] = skill_text
                    result["skill_score"] = archived["trs"]["skill_score"]
                emit("lane_result", {"lane": lane, "result": result})
            except Exception as exc:
                emit("lane_error", {"lane": lane, "error": str(exc)})

        threads = [
            threading.Thread(target=runner, args=("direct",), daemon=True),
            threading.Thread(target=runner, args=("trs",), daemon=True),
        ]
        for thread in threads:
            thread.start()

        completed_lanes = 0
        while completed_lanes < len(threads):
            event_name, payload = events.get()
            try:
                if event_name == "lane_result":
                    results[payload["lane"]] = payload["result"]
                    completed_lanes += 1
                elif event_name == "lane_error":
                    failures.append(payload["error"])
                    completed_lanes += 1
                self._send_sse_event(event_name, payload)
            except BrokenPipeError:
                return

        for thread in threads:
            thread.join(timeout=0.1)

        try:
            if failures:
                self._send_sse_event("error", {"error": failures[0]})
            else:
                self._send_sse_event(
                    "summary",
                    {
                        "model": model_payload(config),
                        "summary": compute_live_summary(results["direct"], results["trs"]),
                    },
                )
            self._send_sse_event("done", {"ok": not failures})
            self.close_connection = True
        except BrokenPipeError:
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            payload = self._read_json_body()
            example, config = self._resolve_request(payload)

            if parsed.path == "/api/run":
                live = serialize_live_comparison(example, config)
                self._send_json(
                    {
                        "ok": True,
                        "exampleId": example["id"],
                        "live": live,
                    }
                )
                return

            if parsed.path == "/api/run_stream":
                self._handle_stream_run(example, config)
                return

            self._send_json({"error": f"Unknown endpoint: {parsed.path}"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)


class DemoServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[DemoHandler]) -> None:
        super().__init__(server_address, handler_class)
        payload = load_examples_payload()
        self.examples_payload = payload
        self.examples_by_id = {example["id"]: example for example in payload["examples"]}


def main() -> None:
    host = os.environ.get("TRS_DEMO_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("TRS_DEMO_PORT", "8080")))
    httpd = DemoServer((host, port), DemoHandler)
    print(f"TRS demo listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
