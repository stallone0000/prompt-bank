#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
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


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    label: str
    api_model: str
    prompt_template: str
    input_price_yuan_per_million: float
    output_price_yuan_per_million: float


MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "doubao": ModelConfig(
        model_id="doubao",
        label="Doubao Seed 1.8",
        api_model="volcengine/doubao-seed-1-8",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=2.0,
    ),
    "oss": ModelConfig(
        model_id="oss",
        label="GPT-OSS-120B",
        api_model="qiniu/gpt-oss-120b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=1.08,
        output_price_yuan_per_million=5.4,
    ),
}


def load_examples_payload() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing demo data file at {DATA_PATH}. Run `python scripts/build_demo_examples.py` first."
        )
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


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


def call_model(prompt_text: str, config: ModelConfig) -> Dict[str, Any]:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Missing TRS_DEMO_API_KEY (or REBUTTAL_API_KEY) in the server environment.")

    api_url = os.environ.get("TRS_DEMO_API_URL", "http://api.360.cn/v1/chat/completions").strip()
    temperature = float(os.environ.get("TRS_DEMO_TEMPERATURE", "0.7"))
    max_tokens = int(os.environ.get("TRS_DEMO_MAX_TOKENS", "16000"))
    timeout_seconds = int(os.environ.get("TRS_DEMO_TIMEOUT_SECONDS", "300"))

    payload = {
        "model": config.api_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "content_filter": False,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.9,
        "top_k": 0,
        "repetition_penalty": 1.05,
        "num_beams": 1,
        "user": "trs_demo_web",
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Host": "api.360.cn",
        },
        method="POST",
    )

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
    usage = parsed.get("usage", {})
    reasoning_text = message.get("reasoning_content", "") or ""
    answer_text = message.get("content", "") or ""
    prompt_tokens = int(usage.get("prompt_tokens") or estimate_tokens(prompt_text))
    completion_tokens = int(usage.get("completion_tokens") or estimate_tokens(reasoning_text + "\n" + answer_text))
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)

    return {
        "reasoning_text": reasoning_text,
        "answer_text": answer_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_reasoning_tokens": estimate_tokens(reasoning_text),
        "estimated_answer_tokens": estimate_tokens(answer_text),
        "cost_yuan": round(compute_cost_yuan(prompt_tokens, completion_tokens, config), 6),
    }


def serialize_live_comparison(example: Dict[str, Any], config: ModelConfig) -> Dict[str, Any]:
    question = example["question"]
    skill_text = example["archived"][config.model_id]["trs"]["skill_text"]
    direct_prompt = build_prompt(config.prompt_template, question, "")
    trs_prompt = build_prompt(config.prompt_template, question, skill_text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_direct = pool.submit(call_model, direct_prompt, config)
        future_trs = pool.submit(call_model, trs_prompt, config)
        direct = future_direct.result()
        trs = future_trs.result()

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
        "model": {
            "id": config.model_id,
            "label": config.label,
            "apiModel": config.api_model,
            "paperPricing": {
                "inputYuanPerMillion": config.input_price_yuan_per_million,
                "outputYuanPerMillion": config.output_price_yuan_per_million,
            },
        },
        "direct": direct,
        "trs": {
            **trs,
            "skill_text": skill_text,
            "skill_score": example["archived"][config.model_id]["trs"]["skill_score"],
        },
        "summary": {
            "estimated_reasoning_tokens_saved": reasoning_saved,
            "estimated_reasoning_reduction_pct": reasoning_reduction_pct,
            "total_tokens_saved": total_saved,
            "cost_saved_yuan": cost_saved,
        },
    }


class DemoHandler(SimpleHTTPRequestHandler):
    server_version = "TRSDemo/0.1"

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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._send_json({"error": f"Unknown endpoint: {parsed.path}"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            payload = json.loads(body or "{}")
            example_id = payload.get("exampleId", "")
            model_id = payload.get("modelId", "")

            if model_id not in MODEL_CONFIGS:
                raise ValueError(f"Unsupported modelId: {model_id}")

            example = self.server.examples_by_id.get(example_id)
            if not example:
                raise ValueError(f"Unknown exampleId: {example_id}")

            live = serialize_live_comparison(example, MODEL_CONFIGS[model_id])
            self._send_json(
                {
                    "ok": True,
                    "exampleId": example_id,
                    "live": live,
                }
            )
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
