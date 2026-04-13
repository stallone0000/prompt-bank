#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import queue
import re
import socket
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
HINT_PATTERN = re.compile(r"\bhints?\b", re.IGNORECASE)
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
RETRYABLE_ERROR_SNIPPETS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remote end closed",
    "incomplete read",
    "broken pipe",
    "eof occurred",
)
RETRYABLE_HTTP_DETAIL_SNIPPETS = (
    "third_request_id",
    "original_error",
    "temporarily unavailable",
    "upstream",
    "timeout",
    "too many requests",
    "rate limit",
    "bad gateway",
    "gateway",
    "forbidden",
)
TRS_SOURCE_LABELS = {
    "doubao_trs": "Doubao TRS Archive",
    "oss_trs": "GPT-OSS TRS Archive",
    "gemini_trs": "Gemini TRS Archive",
}
RETRIEVAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "find",
    "show",
    "prove",
    "such",
    "then",
    "than",
    "have",
    "has",
    "are",
    "let",
    "given",
    "determine",
    "which",
    "what",
    "when",
    "where",
    "whose",
    "value",
    "values",
    "equation",
    "function",
    "triangle",
    "integral",
    "limit",
    "solve",
}
REPETITION_GUARD_REASON = "repetition_guard"
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
    provider: str
    family: str
    label: str
    api_model: str
    prompt_template: str
    input_price_yuan_per_million: float | None
    output_price_yuan_per_million: float | None
    supports_reasoning_trace: bool
    max_tokens: int = 32000
    max_tokens_param: str = "max_tokens"
    temperature_override: float | None = None
    extra_body: Dict[str, Any] | None = None


MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "doubao": ModelConfig(
        model_id="doubao",
        company="Doubao",
        provider="ByteDance",
        family="Doubao",
        label="Doubao Seed 1.8",
        api_model="volcengine/doubao-seed-1-8",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=2.0,
        supports_reasoning_trace=True,
    ),
    "doubao2pro": ModelConfig(
        model_id="doubao2pro",
        company="Doubao",
        provider="ByteDance",
        family="Doubao",
        label="Doubao Seed 2.0 Pro",
        api_model="volcengine/doubao-seed-2-0-pro",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=3.2,
        output_price_yuan_per_million=16.0,
        supports_reasoning_trace=True,
    ),
    "oss": ModelConfig(
        model_id="oss",
        company="GPT",
        provider="Qiniu",
        family="GPT",
        label="GPT-OSS-120B",
        api_model="qiniu/gpt-oss-120b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=1.08,
        output_price_yuan_per_million=5.4,
        supports_reasoning_trace=False,
    ),
    "oss20": ModelConfig(
        model_id="oss20",
        company="GPT",
        provider="Qiniu",
        family="GPT",
        label="GPT-OSS-20B",
        api_model="qiniu/gpt-oss-20b",
        prompt_template=PROMPT_COD,
        input_price_yuan_per_million=0.72,
        output_price_yuan_per_million=3.6,
        supports_reasoning_trace=True,
    ),
    "gemini": ModelConfig(
        model_id="gemini",
        company="Gemini",
        provider="CloudSway",
        family="Gemini",
        label="Gemini 3 Flash",
        api_model="cloudsway/gemini-3-flash-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=2.52,
        output_price_yuan_per_million=15.12,
        supports_reasoning_trace=False,
    ),
    "qwen35plus": ModelConfig(
        model_id="qwen35plus",
        company="Qwen",
        provider="Alibaba",
        family="Qwen",
        label="Qwen 3.5 Plus",
        api_model="alibaba/qwen3.5-plus",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.8,
        output_price_yuan_per_million=4.8,
        supports_reasoning_trace=True,
    ),
    "qwen35flash": ModelConfig(
        model_id="qwen35flash",
        company="Qwen",
        provider="Alibaba",
        family="Qwen",
        label="Qwen 3.5 Flash",
        api_model="alibaba/qwen3.5-flash",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.2,
        output_price_yuan_per_million=2.0,
        supports_reasoning_trace=True,
    ),
    "qwen36plus": ModelConfig(
        model_id="qwen36plus",
        company="Qwen",
        provider="Qwen",
        family="Qwen",
        label="Qwen 3.6 Plus",
        api_model="qwen/qwen3.6-plus",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.0,
        output_price_yuan_per_million=12.0,
        supports_reasoning_trace=True,
    ),
    "glm5": ModelConfig(
        model_id="glm5",
        company="GLM",
        provider="Z.AI",
        family="GLM",
        label="GLM-5",
        api_model="z-ai/glm-5",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.8,
        output_price_yuan_per_million=12.6,
        supports_reasoning_trace=True,
    ),
    "glm51": ModelConfig(
        model_id="glm51",
        company="GLM",
        provider="Z.AI",
        family="GLM",
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
        provider="MiniMax",
        family="MiniMax",
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
        provider="MiniMax",
        family="MiniMax",
        label="MiniMax M2.7 Highspeed",
        api_model="minimax/MiniMax-M2.7-highspeed",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=4.2,
        output_price_yuan_per_million=16.8,
        supports_reasoning_trace=True,
    ),
    "kimi25": ModelConfig(
        model_id="kimi25",
        company="Kimi",
        provider="Moonshot via Qiniu",
        family="Kimi",
        label="Kimi K2.5",
        api_model="qiniu/kimi-k2.5",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.8,
        output_price_yuan_per_million=14.7,
        supports_reasoning_trace=True,
    ),
    "gpt54": ModelConfig(
        model_id="gpt54",
        company="GPT",
        provider="OpenAI via Qiniu",
        family="GPT",
        label="GPT-5.4",
        api_model="qiniu/openai/gpt-5.4",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=18.25,
        output_price_yuan_per_million=109.5,
        supports_reasoning_trace=False,
        max_tokens_param="max_completion_tokens",
        temperature_override=1.0,
    ),
    "gpt52": ModelConfig(
        model_id="gpt52",
        company="GPT",
        provider="Microsoft / OpenAI",
        family="GPT",
        label="GPT-5.2",
        api_model="microsoft/openai/gpt-5.2",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=12.6,
        output_price_yuan_per_million=100.8,
        supports_reasoning_trace=False,
        max_tokens_param="max_completion_tokens",
        temperature_override=1.0,
    ),
    "claudeopus46": ModelConfig(
        model_id="claudeopus46",
        company="Claude",
        provider="Anthropic",
        family="Claude",
        label="Claude Opus 4.6",
        api_model="anthropic/claude-opus-4.6",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=36.5,
        output_price_yuan_per_million=273.75,
        supports_reasoning_trace=False,
    ),
    "claudesonnet46": ModelConfig(
        model_id="claudesonnet46",
        company="Claude",
        provider="Anthropic",
        family="Claude",
        label="Claude Sonnet 4.6",
        api_model="anthropic/claude-sonnet-4-6",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=18.576,
        output_price_yuan_per_million=92.88,
        supports_reasoning_trace=False,
    ),
    "claudehaiku45": ModelConfig(
        model_id="claudehaiku45",
        company="Claude",
        provider="Anthropic",
        family="Claude",
        label="Claude Haiku 4.5",
        api_model="anthropic/claude-haiku-4.5",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=7.2,
        output_price_yuan_per_million=36.0,
        supports_reasoning_trace=False,
    ),
    "grok4": ModelConfig(
        model_id="grok4",
        company="Grok",
        provider="xAI",
        family="Grok",
        label="Grok-4",
        api_model="xai/grok-4",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=22.0,
        output_price_yuan_per_million=110.0,
        supports_reasoning_trace=False,
    ),
    "grok4fast": ModelConfig(
        model_id="grok4fast",
        company="Grok",
        provider="Qiniu",
        family="Grok",
        label="Grok-4 Fast",
        api_model="qiniu/grok-4-fast",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=2.88,
        output_price_yuan_per_million=7.2,
        supports_reasoning_trace=False,
    ),
    "gemini31pro": ModelConfig(
        model_id="gemini31pro",
        company="Gemini",
        provider="Google",
        family="Gemini",
        label="Gemini 3.1 Pro Preview",
        api_model="google/gemini-3.1-pro-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=14.6,
        output_price_yuan_per_million=87.6,
        supports_reasoning_trace=False,
    ),
    "deepseek32": ModelConfig(
        model_id="deepseek32",
        company="DeepSeek",
        provider="Qiniu",
        family="DeepSeek",
        label="DeepSeek V3.2",
        api_model="qiniu/deepseek-v3.2",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=2.0,
        output_price_yuan_per_million=3.0,
        supports_reasoning_trace=True,
        extra_body={"thinking": {"type": "enabled"}},
    ),
}


ARCHIVED_FALLBACK_PRIORITY = [
    "doubao",
    "gemini",
    "oss",
    "qwen35plus",
    "glm5",
    "minimax25hs",
    "kimi25",
]


def resolve_archived_example_for_model(
    archived_by_model: Dict[str, Any], model_id: str
) -> Dict[str, Any]:
    if model_id in archived_by_model:
        return archived_by_model[model_id]

    target_family = MODEL_CONFIGS[model_id].family
    for fallback_model_id, fallback_config in MODEL_CONFIGS.items():
        if fallback_model_id in archived_by_model and fallback_config.family == target_family:
            return archived_by_model[fallback_model_id]

    for fallback_model_id in ARCHIVED_FALLBACK_PRIORITY:
        if fallback_model_id in archived_by_model:
            return archived_by_model[fallback_model_id]

    if archived_by_model:
        return next(iter(archived_by_model.values()))

    raise KeyError(f"Example archive is missing model data for {model_id}.")


def load_examples_payload() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing demo data file at {DATA_PATH}. Run `python scripts/build_demo_examples.py` first."
        )
    with DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    for example in payload.get("examples", []):
        archived_by_model = example.get("archived", {})
        example["archived"] = {
            model_id: deepcopy(resolve_archived_example_for_model(archived_by_model, model_id))
            for model_id in MODEL_CONFIGS
        }

    payload["models"] = {
        model_id: {
            **payload.get("models", {}).get(model_id, {}),
            "company": config.company,
            "provider": config.provider,
            "family": config.family,
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


def tokenize_retrieval_text(text: str) -> list[str]:
    tokens = []
    for token in TOKEN_PATTERN.findall((text or "").lower()):
        if len(token) <= 1:
            continue
        if token in RETRIEVAL_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def source_label_for_key(source_key: str) -> str:
    return TRS_SOURCE_LABELS.get(source_key, source_key.replace("_", " ").title())


def build_skill_corpus(payload: Dict[str, Any]) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []
    doc_freq: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str]] = set()

    for source_key, path_str in payload.get("sources", {}).items():
        if not source_key.endswith("_trs"):
            continue
        path = Path(path_str)
        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                question = (item.get("question") or "").strip()
                skill_text = (item.get("heuristic_used") or "").strip()
                if not question or not skill_text:
                    continue

                dedupe_key = (question, skill_text)
                if dedupe_key in seen_pairs:
                    continue
                seen_pairs.add(dedupe_key)

                token_set = set(tokenize_retrieval_text(question))
                if not token_set:
                    continue

                doc_freq.update(token_set)
                entries.append(
                    {
                        "question_id": item.get("question_id") or "",
                        "question": question,
                        "answer": (item.get("answer") or "").strip(),
                        "topic": (item.get("topic") or "").strip(),
                        "difficulty": item.get("difficulty"),
                        "skill_text": skill_text,
                        "skill_score": float(item.get("heuristic_score") or 0.0),
                        "source_key": source_key,
                        "source_label": source_label_for_key(source_key),
                        "token_set": token_set,
                    }
                )

    total_docs = len(entries)
    idf = {
        token: math.log((1 + total_docs) / (1 + df)) + 1.0
        for token, df in doc_freq.items()
    }
    return {
        "entries": entries,
        "idf": idf,
        "doc_count": total_docs,
    }


def retrieve_skill_entry(question: str, corpus: Dict[str, Any]) -> Dict[str, Any]:
    query = (question or "").strip()
    if not query:
        raise ValueError("Custom mode requires a non-empty question.")

    query_tokens = set(tokenize_retrieval_text(query))
    if not query_tokens:
        raise ValueError("The custom question is too short to retrieve a skill card.")

    entries = corpus.get("entries", [])
    if not entries:
        raise ValueError("No local TRS skill corpus is available for retrieval.")

    best_entry: Dict[str, Any] | None = None
    best_score = float("-inf")

    for entry in entries:
        overlap = query_tokens & entry["token_set"]
        if not overlap:
            continue

        lexical_score = sum(corpus["idf"].get(token, 1.0) for token in overlap)
        coverage = len(overlap) / max(1, len(query_tokens))
        density = len(overlap) / max(1, len(entry["token_set"]))
        score = lexical_score * (0.8 + 0.2 * coverage) + density + entry["skill_score"] * 0.004
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is None:
        best_entry = max(entries, key=lambda item: item["skill_score"])
        best_score = best_entry["skill_score"] * 0.004

    return {
        **best_entry,
        "retrieval_score": round(best_score, 4),
        "matched_tokens": sorted(query_tokens & best_entry["token_set"]),
    }


def summarize_custom_question(question: str, limit: int = 76) -> str:
    first_line = next((line.strip() for line in question.splitlines() if line.strip()), "").strip()
    if not first_line:
        return "Custom Problem"
    if len(first_line) <= limit:
        return first_line
    return first_line[: limit - 1].rstrip() + "…"


def build_custom_example(question: str, reference_answer: str, retrieval: Dict[str, Any]) -> Dict[str, Any]:
    archived_template = {
        "direct": {"verification": "UNKNOWN"},
        "trs": {
            "verification": "UNKNOWN",
            "skill_text": retrieval["skill_text"],
            "skill_score": retrieval["skill_score"],
        },
    }
    return {
        "id": "custom-problem",
        "questionId": "",
        "title": "Custom Problem",
        "subtitle": (
            f"Matched to {retrieval['source_label']}"
            + (f" · {retrieval['topic']}" if retrieval.get("topic") else "")
        ),
        "highlight": "Skill card retrieved from the local TRS archive using lexical overlap.",
        "question": question.strip(),
        "answer": reference_answer.strip(),
        "topic": "Custom Input",
        "difficulty": "User",
        "archived": {
            model_id: deepcopy(archived_template)
            for model_id in MODEL_CONFIGS
        },
        "retrieval": {
            "sourceLabel": retrieval["source_label"],
            "matchedQuestion": retrieval["question"],
            "matchedTopic": retrieval.get("topic") or "",
            "matchedDifficulty": retrieval.get("difficulty"),
            "matchedTokens": retrieval.get("matched_tokens") or [],
            "score": retrieval["retrieval_score"],
        },
        "customTitle": summarize_custom_question(question),
    }


def serialize_custom_preview(example: Dict[str, Any]) -> Dict[str, Any]:
    first_archived = next(iter(example["archived"].values()))
    return {
        "id": example["id"],
        "title": example["customTitle"],
        "subtitle": example["subtitle"],
        "question": example["question"],
        "answer": example["answer"],
        "topic": example["topic"],
        "difficulty": example["difficulty"],
        "skillText": first_archived["trs"]["skill_text"],
        "skillScore": first_archived["trs"]["skill_score"],
        "retrieval": example["retrieval"],
    }


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
    temperature = config.temperature_override
    if temperature is None:
        temperature = float(os.environ.get("TRS_DEMO_TEMPERATURE", "0.7"))

    payload = {
        "model": config.api_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "stream": stream,
        "temperature": temperature,
    }
    payload[config.max_tokens_param] = config.max_tokens
    if config.extra_body:
        payload["extra_body"] = config.extra_body
    return payload


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


def merge_usage(existing: Dict[str, Any], incoming: Dict[str, Any] | None) -> Dict[str, Any]:
    if not incoming:
        return existing

    merged = dict(existing)
    for key, value in incoming.items():
        if isinstance(value, dict):
            merged[key] = merge_usage(merged.get(key, {}) if isinstance(merged.get(key), dict) else {}, value)
            continue

        if key.endswith("_tokens") or key in {"prompt_tokens", "completion_tokens", "total_tokens"}:
            current = parse_usage_int(merged.get(key))
            candidate = parse_usage_int(value)
            if candidate is None:
                continue
            merged[key] = candidate if current is None else max(current, candidate)
            continue

        if value not in (None, ""):
            merged[key] = value
    return merged


def parse_verifier_verdict(content: str) -> str:
    first_line = content.splitlines()[0].strip().upper() if content else ""
    if "INCORRECT" in first_line:
        return "INCORRECT"
    if "CORRECT" in first_line:
        return "CORRECT"
    return first_line or "UNKNOWN"


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def get_live_max_retries() -> int:
    return env_int("TRS_DEMO_MAX_RETRIES", 6)


def get_stream_max_retries() -> int:
    return env_int("TRS_DEMO_STREAM_MAX_RETRIES", max(7, get_live_max_retries()))


def get_verify_max_retries() -> int:
    return env_int("TRS_DEMO_VERIFY_MAX_RETRIES", max(7, get_live_max_retries()))


def get_timeout_seconds() -> int:
    return env_int("TRS_DEMO_TIMEOUT_SECONDS", 300)


def get_verify_timeout_seconds() -> int:
    return env_int("TRS_DEMO_VERIFY_TIMEOUT_SECONDS", 120)


def retry_sleep_seconds(attempt_number: int, *, base: float = 0.6, cap: float = 6.0) -> float:
    exponent = max(0, attempt_number - 1)
    return round(min(cap, base * (1.8**exponent)), 2)


def is_retryable_upstream_error(exc: Exception, formatted_error: str = "") -> bool:
    if isinstance(exc, error.HTTPError):
        if exc.code in RETRYABLE_HTTP_STATUS_CODES:
            return True
        if exc.code in {400, 403}:
            detail = (formatted_error or str(exc)).lower()
            return any(snippet in detail for snippet in RETRYABLE_HTTP_DETAIL_SNIPPETS)
        return False
    if isinstance(exc, (error.URLError, TimeoutError, socket.timeout)):
        return True
    message = str(exc).lower()
    return any(snippet in message for snippet in RETRYABLE_ERROR_SNIPPETS)


def format_upstream_error(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        detail = exc.read().decode("utf-8", errors="replace")
        return f"HTTP {exc.code}: {detail}"
    return str(exc)


def verifier_max_tokens_param(model_name: str) -> str:
    lowered = model_name.lower()
    if "gpt-5" in lowered or "openai/" in lowered:
        return "max_completion_tokens"
    return "max_tokens"


def verify_answer(question_text: str, reference_answer: str, candidate_answer: str) -> Dict[str, Any]:
    verifier_model = get_verify_model()
    cleaned_candidate = (candidate_answer or "").strip()
    max_retries = get_verify_max_retries()
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
        "stream": False,
        "temperature": 0,
    }
    payload[verifier_max_tokens_param(verifier_model)] = 32

    opener = build_opener()
    timeout_seconds = get_verify_timeout_seconds()
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            with opener.open(build_json_api_request(payload), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries or not is_retryable_upstream_error(exc, last_error):
                return {
                    "status": "unknown",
                    "label": "Verifier Retry Failed",
                    "reference_answer": reference_answer,
                    "verifier_model": verifier_model,
                    "verdict": "UNKNOWN",
                    "verifier_response": last_error,
                }
            time.sleep(retry_sleep_seconds(attempt, base=0.8, cap=8.0))

    if parsed is None:
        return {
            "status": "unknown",
            "label": "Verifier Retry Failed",
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


def normalize_repetition_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_repetition_loop(text: str) -> bool:
    normalized = normalize_repetition_text(text)
    if len(normalized) < 180:
        return False

    for width in (36, 48, 64, 80, 96):
        if len(normalized) < width * 3:
            continue
        tail = normalized[-width:]
        if tail * 3 == normalized[-width * 3 :]:
            return True

    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    if len(lines) >= 3 and len(lines[-1]) >= 18 and lines[-1] == lines[-2] == lines[-3]:
        return True
    return False


def summarize_stop_reason(finish_reason: str | None, combined_text: str) -> Dict[str, Any]:
    repeated = detect_repetition_loop(combined_text)
    if finish_reason == REPETITION_GUARD_REASON:
        return {
            "finish_reason": finish_reason,
            "stop_label": "Repetition Guard",
            "stop_warning": "Detected a repetition loop and stopped early.",
            "truncated": True,
            "possible_repetition": True,
        }
    if finish_reason == "length":
        return {
            "finish_reason": finish_reason,
            "stop_label": "Max Length Reached",
            "stop_warning": (
                "Output hit the max-length cap and may be incomplete."
                + (" Possible repetition loop detected." if repeated else "")
            ),
            "truncated": True,
            "possible_repetition": repeated,
        }
    if repeated:
        return {
            "finish_reason": finish_reason,
            "stop_label": "Possible Repetition",
            "stop_warning": "The ending looks repetitive. Check whether the answer was cut off.",
            "truncated": False,
            "possible_repetition": True,
        }
    return {
        "finish_reason": finish_reason,
        "stop_label": None,
        "stop_warning": "",
        "truncated": False,
        "possible_repetition": False,
    }


def build_result(
    question_text: str,
    config: ModelConfig,
    reasoning_text: str,
    answer_text: str,
    usage: Dict[str, Any],
    reference_answer: str,
    finish_reason: str | None,
) -> Dict[str, Any]:
    prompt_tokens = parse_usage_int(usage.get("prompt_tokens"))
    completion_tokens = parse_usage_int(usage.get("completion_tokens"))
    total_tokens = parse_usage_int(usage.get("total_tokens"))
    cost_yuan = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_yuan = round(compute_cost_yuan(prompt_tokens, completion_tokens, config), 6)

    correctness = verify_answer(question_text, reference_answer, answer_text)
    stop_info = summarize_stop_reason(finish_reason, "\n".join([reasoning_text or "", answer_text or ""]))

    return {
        "reasoning_text": reasoning_text or "",
        "answer_text": answer_text or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_yuan": cost_yuan,
        "correctness": correctness,
        "finish_reason": stop_info["finish_reason"],
        "stop_label": stop_info["stop_label"],
        "stop_warning": stop_info["stop_warning"],
        "truncated": stop_info["truncated"],
        "possible_repetition": stop_info["possible_repetition"],
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
        "provider": config.provider,
        "family": config.family,
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
    max_retries = get_live_max_retries()
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            with opener.open(make_api_request(prompt_text, config, stream=False), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries or not is_retryable_upstream_error(exc, last_error):
                raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}") from exc
            time.sleep(retry_sleep_seconds(attempt))

    if parsed is None:
        raise RuntimeError(f"Upstream API request failed after {max_retries} attempts: {last_error}")

    choices = parsed.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})
    usage = parsed.get("usage", {}) or {}
    return build_result(
        question_text=question_text,
        config=config,
        reasoning_text=extract_reasoning_text(message),
        answer_text=extract_answer_text(message),
        usage=usage,
        reference_answer=reference_answer,
        finish_reason=choice.get("finish_reason"),
    )


def stream_model(
    question_text: str,
    prompt_text: str,
    config: ModelConfig,
    reference_answer: str,
    on_delta: Callable[[str, str], None],
    on_retry: Callable[[int, int, str], None],
    on_fallback: Callable[[str], None],
) -> Dict[str, Any]:
    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    max_retries = get_stream_max_retries()
    last_error = ""

    for attempt in range(1, max_retries + 1):
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        usage: Dict[str, Any] = {}
        finish_reason: str | None = None

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
                        usage = merge_usage(usage, chunk["usage"])
                    choices = chunk.get("choices", [])
                    choice = choices[0] if choices else {}
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta", {})
                    reasoning_piece = extract_reasoning_text(delta)
                    answer_piece = extract_answer_text(delta)
                    if reasoning_piece:
                        reasoning_parts.append(reasoning_piece)
                        on_delta("reasoning", reasoning_piece)
                    if answer_piece:
                        answer_parts.append(answer_piece)
                        on_delta("answer", answer_piece)
                    combined_text = "\n".join(["".join(reasoning_parts), "".join(answer_parts)])
                    if detect_repetition_loop(combined_text):
                        finish_reason = REPETITION_GUARD_REASON
                        break

            return build_result(
                question_text=question_text,
                config=config,
                reasoning_text="".join(reasoning_parts),
                answer_text="".join(answer_parts),
                usage=usage,
                reference_answer=reference_answer,
                finish_reason=finish_reason,
            )
        except Exception as exc:
            last_error = format_upstream_error(exc)
            if attempt >= max_retries or not is_retryable_upstream_error(exc, last_error):
                break
            on_retry(attempt + 1, max_retries, last_error)
            time.sleep(retry_sleep_seconds(attempt))

    on_fallback(last_error)
    try:
        return call_model(question_text, prompt_text, config, reference_answer)
    except Exception as exc:
        fallback_error = format_upstream_error(exc)
        raise RuntimeError(
            f"Streaming failed after {max_retries} attempts: {last_error}; "
            f"fallback non-stream request failed: {fallback_error}"
        ) from exc


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

    def _build_custom_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        question = (payload.get("question") or "").strip()
        reference_answer = (payload.get("referenceAnswer") or payload.get("answer") or "").strip()
        if not question:
            raise ValueError("Custom mode requires a question.")
        if not reference_answer:
            raise ValueError("Custom mode requires a reference answer.")
        retrieval = retrieve_skill_entry(question, self.server.skill_corpus)
        return build_custom_example(question, reference_answer, retrieval)

    def _resolve_request(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], ModelConfig]:
        model_id = payload.get("modelId", "")

        if model_id not in MODEL_CONFIGS:
            raise ValueError(f"Unsupported modelId: {model_id}")

        if payload.get("question") or payload.get("referenceAnswer") or payload.get("answer"):
            skill_text = (payload.get("skillText") or "").strip()
            skill_score = payload.get("skillScore")
            custom_preview = self._build_custom_preview(payload)
            if skill_text:
                for archived in custom_preview["archived"].values():
                    archived["trs"]["skill_text"] = skill_text
                    archived["trs"]["skill_score"] = float(skill_score or 0.0)
            if payload.get("title"):
                custom_preview["title"] = str(payload["title"])
            if payload.get("subtitle"):
                custom_preview["subtitle"] = str(payload["subtitle"])
            if payload.get("topic"):
                custom_preview["topic"] = str(payload["topic"])
            if payload.get("difficulty"):
                custom_preview["difficulty"] = payload["difficulty"]
            return custom_preview, MODEL_CONFIGS[model_id]

        example_id = payload.get("exampleId", "")
        example = self.server.examples_by_id.get(example_id)
        if not example:
            raise ValueError(f"Unknown exampleId: {example_id}")

        return example, MODEL_CONFIGS[model_id]

    def _handle_stream_run(self, example: Dict[str, Any], config: ModelConfig, run_id: int | None) -> None:
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
                "runId": run_id,
                "mode": "custom" if example["id"] == "custom-problem" else "example",
                "questionTitle": example.get("title") or "",
                "questionSubtitle": example.get("subtitle") or "",
                "topic": example.get("topic") or "",
                "difficulty": example.get("difficulty"),
                "retrieval": example.get("retrieval") or None,
                "retrievedSkill": skill_text,
                "model": model_payload(config),
                "referenceAnswer": reference_answer,
            },
        )

        events: queue.Queue[tuple[str, Dict[str, Any]]] = queue.Queue()
        results: Dict[str, Dict[str, Any]] = {}
        failures: list[str] = []

        def emit(event_name: str, payload: Dict[str, Any]) -> None:
            if run_id is not None and "runId" not in payload:
                payload = {
                    "runId": run_id,
                    **payload,
                }
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
                    on_fallback=lambda error_message: emit(
                        "lane_fallback",
                        {
                            "lane": lane,
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
                        "runId": run_id,
                        "model": model_payload(config),
                        "summary": compute_live_summary(results["direct"], results["trs"]),
                    },
                )
            self._send_sse_event("done", {"runId": run_id, "ok": not failures})
            self.close_connection = True
        except BrokenPipeError:
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            payload = self._read_json_body()

            if parsed.path == "/api/retrieve_skill":
                preview = self._build_custom_preview(payload)
                self._send_json({"ok": True, "custom": serialize_custom_preview(preview)})
                return

            example, config = self._resolve_request(payload)
            run_id = payload.get("runId")

            if parsed.path == "/api/run":
                live = serialize_live_comparison(example, config)
                self._send_json(
                    {
                        "ok": True,
                        "exampleId": example["id"],
                        "mode": "custom" if example["id"] == "custom-problem" else "example",
                        "live": live,
                    }
                )
                return

            if parsed.path == "/api/run_stream":
                self._handle_stream_run(example, config, run_id)
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
        self.skill_corpus = build_skill_corpus(payload)


def main() -> None:
    host = os.environ.get("TRS_DEMO_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("TRS_DEMO_PORT", "8080")))
    httpd = DemoServer((host, port), DemoHandler)
    print(f"TRS demo listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
