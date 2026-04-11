#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
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

OPTION_RE = re.compile(r"\b([A-E])\b", re.IGNORECASE)
NUMERIC_RE = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\d+/\d+)")


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    label: str
    api_model: str
    prompt_template: str
    input_price_yuan_per_million: float
    output_price_yuan_per_million: float
    supports_reasoning_trace: bool


MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "doubao": ModelConfig(
        model_id="doubao",
        label="Doubao Seed 1.8",
        api_model="volcengine/doubao-seed-1-8",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=2.0,
        supports_reasoning_trace=True,
    ),
    "oss": ModelConfig(
        model_id="oss",
        label="GPT-OSS-120B",
        api_model="qiniu/gpt-oss-120b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=1.08,
        output_price_yuan_per_million=5.4,
        supports_reasoning_trace=False,
    ),
    "gemini": ModelConfig(
        model_id="gemini",
        label="Gemini 3 Flash",
        api_model="cloudsway/gemini-3-flash-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=2.52,
        output_price_yuan_per_million=15.12,
        supports_reasoning_trace=False,
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
            "label": config.label,
            "apiModel": config.api_model,
            "supportsReasoningTrace": config.supports_reasoning_trace,
            "paperPricing": {
                "inputYuanPerMillion": config.input_price_yuan_per_million,
                "outputYuanPerMillion": config.output_price_yuan_per_million,
            },
        }
        for model_id, config in MODEL_CONFIGS.items()
    }
    return payload


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 2)


def compute_cost_yuan(prompt_tokens: int, completion_tokens: int, config: ModelConfig) -> float:
    return (
        prompt_tokens / 1_000_000 * config.input_price_yuan_per_million
        + completion_tokens / 1_000_000 * config.output_price_yuan_per_million
    )


def build_prompt(template: str, question: str, skill_text: str) -> str:
    return template.replace("{SOLVING_HINTS}", skill_text).replace("{PROBLEM}", question)


def get_api_key() -> str:
    return os.environ.get("TRS_DEMO_API_KEY") or os.environ.get("REBUTTAL_API_KEY", "")


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
        "max_tokens": int(os.environ.get("TRS_DEMO_MAX_TOKENS", "16000")),
        "top_p": 0.9,
        "top_k": 0,
        "repetition_penalty": 1.05,
        "num_beams": 1,
        "user": "trs_demo_web",
    }


def make_api_request(prompt_text: str, config: ModelConfig, stream: bool) -> request.Request:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Missing TRS_DEMO_API_KEY (or REBUTTAL_API_KEY) in the server environment.")

    api_url = os.environ.get("TRS_DEMO_API_URL", "http://api.360.cn/v1/chat/completions").strip()
    body = json.dumps(build_api_payload(prompt_text, config, stream)).encode("utf-8")
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


def strip_boxed(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = re.sub(r"\\boxed\s*{([^{}]+)}", r"\1", current)
    return current


def clean_answer_text(text: str) -> str:
    cleaned = strip_boxed(text)
    for source, target in [
        ("\\(", ""),
        ("\\)", ""),
        ("\\[", ""),
        ("\\]", ""),
        ("$", ""),
        ("**", ""),
        ("`", ""),
        ("\u2212", "-"),
    ]:
        cleaned = cleaned.replace(source, target)
    return cleaned.strip()


def normalize_answer(text: str) -> str:
    cleaned = clean_answer_text(text)
    cleaned = re.sub(
        r"(?i)(final answer|answer|the answer is|答案是|最终答案是|答案为|最终答案为|所以答案是|因此答案是)\s*[:：]?\s*",
        " ",
        cleaned,
    )
    cleaned = cleaned.strip(" \n\t\r。．.,;:!！？()[]{}<>")
    return re.sub(r"\s+", "", cleaned).lower()


def extract_option_answer(text: str) -> str:
    matches = OPTION_RE.findall(clean_answer_text(text).upper())
    return matches[-1].upper() if matches else ""


def extract_numeric_answer(text: str) -> str:
    matches = NUMERIC_RE.findall(clean_answer_text(text).replace(",", ""))
    return matches[-1] if matches else ""


def evaluate_correctness(answer_text: str, reference_answer: str) -> Dict[str, str]:
    reference = reference_answer.strip()
    prediction = answer_text.strip()
    extracted = ""
    status = "unverified"
    label = "Heuristic Match Unclear"

    if not prediction:
        status = "missing"
        label = "No Final Answer"
    elif re.fullmatch(r"[A-E]", reference, re.IGNORECASE):
        extracted = extract_option_answer(prediction)
        if extracted:
            status = "correct" if extracted.upper() == reference.upper() else "incorrect"
            label = "Correct" if status == "correct" else "Incorrect"
    elif re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\d+/\d+)", reference):
        extracted = extract_numeric_answer(prediction)
        if extracted:
            status = "correct" if normalize_answer(extracted) == normalize_answer(reference) else "incorrect"
            label = "Correct" if status == "correct" else "Incorrect"
    else:
        extracted = clean_answer_text(prediction)
        if normalize_answer(extracted):
            matched = normalize_answer(extracted) == normalize_answer(reference)
            if not matched:
                matched = normalize_answer(extracted).endswith(normalize_answer(reference))
            status = "correct" if matched else "incorrect"
            label = "Correct" if matched else "Incorrect"

    return {
        "status": status,
        "label": label,
        "reference_answer": reference_answer,
        "extracted_answer": extracted,
    }


def build_result(
    prompt_text: str,
    config: ModelConfig,
    reasoning_text: str,
    answer_text: str,
    usage: Dict[str, Any],
    reference_answer: str,
) -> Dict[str, Any]:
    prompt_tokens = int(usage.get("prompt_tokens") or estimate_tokens(prompt_text))
    completion_tokens = int(usage.get("completion_tokens") or estimate_tokens(reasoning_text + "\n" + answer_text))
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    reported_reasoning_tokens = int(
        (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    )

    return {
        "reasoning_text": reasoning_text,
        "answer_text": answer_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reported_reasoning_tokens": reported_reasoning_tokens,
        "estimated_reasoning_tokens": estimate_tokens(reasoning_text),
        "estimated_answer_tokens": estimate_tokens(answer_text),
        "cost_yuan": round(compute_cost_yuan(prompt_tokens, completion_tokens, config), 6),
        "correctness": evaluate_correctness(answer_text, reference_answer),
    }


def compute_live_summary(direct: Dict[str, Any], trs: Dict[str, Any]) -> Dict[str, Any]:
    reasoning_saved = direct["estimated_reasoning_tokens"] - trs["estimated_reasoning_tokens"]
    total_saved = direct["total_tokens"] - trs["total_tokens"]
    cost_saved = round(direct["cost_yuan"] - trs["cost_yuan"], 6)
    reasoning_reduction_pct = 0.0
    if direct["estimated_reasoning_tokens"] > 0:
        reasoning_reduction_pct = round(
            reasoning_saved / direct["estimated_reasoning_tokens"] * 100,
            2,
        )
    return {
        "estimated_reasoning_tokens_saved": reasoning_saved,
        "estimated_reasoning_reduction_pct": reasoning_reduction_pct,
        "total_tokens_saved": total_saved,
        "cost_saved_yuan": cost_saved,
    }


def model_payload(config: ModelConfig) -> Dict[str, Any]:
    return {
        "id": config.model_id,
        "label": config.label,
        "apiModel": config.api_model,
        "supportsReasoningTrace": config.supports_reasoning_trace,
        "paperPricing": {
            "inputYuanPerMillion": config.input_price_yuan_per_million,
            "outputYuanPerMillion": config.output_price_yuan_per_million,
        },
    }


def call_model(prompt_text: str, config: ModelConfig, reference_answer: str) -> Dict[str, Any]:
    req = make_api_request(prompt_text, config, stream=False)
    timeout_seconds = int(os.environ.get("TRS_DEMO_TIMEOUT_SECONDS", "300"))
    opener = build_opener()
    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    parsed = json.loads(raw)
    choices = parsed.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    usage = parsed.get("usage", {}) or {}
    return build_result(
        prompt_text=prompt_text,
        config=config,
        reasoning_text=message.get("reasoning_content", "") or "",
        answer_text=message.get("content", "") or "",
        usage=usage,
        reference_answer=reference_answer,
    )


def stream_model(
    prompt_text: str,
    config: ModelConfig,
    reference_answer: str,
    on_delta: Callable[[str, str], None],
) -> Dict[str, Any]:
    req = make_api_request(prompt_text, config, stream=True)
    timeout_seconds = int(os.environ.get("TRS_DEMO_TIMEOUT_SECONDS", "300"))
    opener = build_opener()
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    usage: Dict[str, Any] = {}

    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices", [])
                delta = choices[0].get("delta", {}) if choices else {}
                reasoning_piece = delta.get("reasoning_content", "") or ""
                answer_piece = delta.get("content", "") or ""
                if reasoning_piece:
                    reasoning_parts.append(reasoning_piece)
                    on_delta("reasoning", reasoning_piece)
                if answer_piece:
                    answer_parts.append(answer_piece)
                    on_delta("answer", answer_piece)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    return build_result(
        prompt_text=prompt_text,
        config=config,
        reasoning_text="".join(reasoning_parts),
        answer_text="".join(answer_parts),
        usage=usage,
        reference_answer=reference_answer,
    )


def serialize_live_comparison(example: Dict[str, Any], config: ModelConfig) -> Dict[str, Any]:
    question = example["question"]
    reference_answer = example["answer"]
    skill_text = example["archived"][config.model_id]["trs"]["skill_text"]
    direct_prompt = build_prompt(config.prompt_template, question, "")
    trs_prompt = build_prompt(config.prompt_template, question, skill_text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_direct = pool.submit(call_model, direct_prompt, config, reference_answer)
        future_trs = pool.submit(call_model, trs_prompt, config, reference_answer)
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
        self.send_header("Connection", "keep-alive")
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
            "direct": build_prompt(config.prompt_template, question, ""),
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
                    prompt_text=prompts[lane],
                    config=config,
                    reference_answer=reference_answer,
                    on_delta=lambda kind, text: emit("lane_delta", {"lane": lane, "kind": kind, "text": text}),
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
