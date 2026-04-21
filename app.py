#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import ipaddress
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

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATA_PATH = APP_DIR / "data" / "demo_examples.json"
BENCHMARK_GROUPS_PATH = APP_DIR / "data" / "benchmark_example_groups.json"
EXAMPLE_PREVIEW_MAP_PATH = APP_DIR / "data" / "example_preview_map.json"
BENCHMARK_DIRECT_ACCURACY_PATH = APP_DIR / "data" / "benchmark_direct_accuracy.json"
DEEPMATH_SKILL_CORPUS_PATH = APP_DIR / "data" / "deepmath_103k_oss_skill_corpus.jsonl.gz"
AOPS_SKILL_CORPUS_PATH = APP_DIR / "data" / "aops_skill_corpus.jsonl.gz"
RUN_QUOTA_STORE_PATH = APP_DIR / "data" / "run_quota_store.json"
LEGACY_SKILL_CORPUS_PATH = APP_DIR / "data" / "trs_skill_corpus.jsonl"
RUN_QUOTA_MAX_RUNS = max(1, int(os.environ.get("TRS_DEMO_RUN_QUOTA_MAX_RUNS", "10")))
RUN_QUOTA_WINDOW_SECONDS = max(60, int(os.environ.get("TRS_DEMO_RUN_QUOTA_WINDOW_SECONDS", "86400")))
RUN_QUOTA_HASH_SALT = os.environ.get("TRS_DEMO_RUN_QUOTA_SALT", "trs-demo-run-quota")
RUN_QUOTA_REDIS_URL = (os.environ.get("TRS_DEMO_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()
RUN_QUOTA_REDIS_KEY_PREFIX = (
    os.environ.get("TRS_DEMO_REDIS_PREFIX", "trs-demo:run-quota").strip() or "trs-demo:run-quota"
)
MAX_REQUEST_BYTES = max(4096, int(os.environ.get("TRS_DEMO_MAX_REQUEST_BYTES", str(128 * 1024))))
MAX_CUSTOM_QUESTION_CHARS = max(256, int(os.environ.get("TRS_DEMO_MAX_CUSTOM_QUESTION_CHARS", "16000")))
MAX_REFERENCE_ANSWER_CHARS = max(32, int(os.environ.get("TRS_DEMO_MAX_REFERENCE_ANSWER_CHARS", "4000")))
MAX_OPTIONAL_FIELD_CHARS = max(32, int(os.environ.get("TRS_DEMO_MAX_OPTIONAL_FIELD_CHARS", "240")))
MAX_CONCURRENT_RUNS = max(1, int(os.environ.get("TRS_DEMO_MAX_CONCURRENT_RUNS", "2")))
MAX_CONCURRENT_RETRIEVALS = max(1, int(os.environ.get("TRS_DEMO_MAX_CONCURRENT_RETRIEVALS", "2")))
DEEPMATH_SKILL_CORPUS_CANDIDATES = (
    {
        "path": DEEPMATH_SKILL_CORPUS_PATH,
        "format": "deployable",
        "label": "DeepMath-103K",
    },
    {
        "path": APP_DIR.parent / "DeepMath-103K" / "cot-bank" / "deepmath_train_oss_distillation_verify_with_heuristics.jsonl",
        "format": "heuristic",
        "source_key": "oss_103k",
        "source_label": "DeepMath-103K",
    },
    {
        "path": APP_DIR.parent / "DeepMath-103K" / "cot-bank" / "deepmath_train_doubao_distillation_verify_with_heuristics.jsonl",
        "format": "heuristic",
        "source_key": "doubao_103k",
        "source_label": "DeepMath-103K",
    },
    {
        "path": APP_DIR.parent / "DeepMath-103K" / "cot-bank" / "deepmath_train_oss_distillation_verify_with_heuristics_rest.jsonl",
        "format": "heuristic",
        "source_key": "oss_93k",
        "source_label": "DeepMath-93K",
    },
    {
        "path": APP_DIR.parent / "DeepMath-103K" / "cot-bank" / "deepmath_train_doubao_distillation_verify_with_heuristics_rest.jsonl",
        "format": "heuristic",
        "source_key": "doubao_93k",
        "source_label": "DeepMath-93K",
    },
    {
        "path": LEGACY_SKILL_CORPUS_PATH,
        "format": "deployable",
        "label": "DeepMath deployable skill archive",
    },
)
AOPS_SKILL_CORPUS_CANDIDATES = (
    {
        "path": AOPS_SKILL_CORPUS_PATH,
        "format": "deployable",
        "label": "AoPS",
    },
    {
        "path": APP_DIR.parent / "AoPS-wiki" / "results" / "aops_skill_cards_complete_full_incorrect_priority.jsonl",
        "format": "aops",
        "source_key": "aops",
        "source_label": "AoPS",
    },
)
SKILL_DATASET_OPTIONS = (
    {
        "id": "deepmath",
        "label": "DeepMath-103K",
        "candidates": DEEPMATH_SKILL_CORPUS_CANDIDATES,
        "default_selected": True,
    },
    {
        "id": "aops",
        "label": "AoPS",
        "candidates": AOPS_SKILL_CORPUS_CANDIDATES,
        "default_selected": True,
    },
)
DEFAULT_SELECTED_SKILL_DATASET_IDS = tuple(
    option["id"] for option in SKILL_DATASET_OPTIONS if option["default_selected"]
)

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
THINK_OPEN_TAG = "<think>"
THINK_CLOSE_TAG = "</think>"
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
NO_EXPERIENCE_SKILL_TEXT = "No experience."
CLAUDE_THINKING_EXTRA_BODY = {
    "thinking": {
        "type": "enabled",
        "budget_tokens": 20000,
    }
}
CLAUDE_ADAPTIVE_THINKING_EXTRA_BODY = {
    "thinking": {
        "type": "adaptive",
        "effort": "high",
        "display": "summarized",
    }
}
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

Respond with exactly one token: CORRECT or INCORRECT.
""".strip()


class RunQuotaExceeded(RuntimeError):
    def __init__(self, status: Dict[str, Any]) -> None:
        self.status = status
        super().__init__(status.get("message") or "Daily run limit reached.")


class RequestTooLarge(ValueError):
    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        super().__init__(f"Request body exceeds the {limit_bytes} byte limit.")


class RunCapacityExceeded(RuntimeError):
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        super().__init__(f"The demo is busy right now. Please retry in a moment. ({capacity} active runs max)")


class RetrievalCapacityExceeded(RuntimeError):
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        super().__init__(f"Skill retrieval is busy right now. Please retry in a moment. ({capacity} active retrievals max)")


class RunCancelledError(RuntimeError):
    pass


def hash_client_ip(client_ip: str) -> str:
    return hashlib.sha256(f"{RUN_QUOTA_HASH_SALT}:{client_ip}".encode("utf-8")).hexdigest()


class RunQuotaStore:
    def __init__(self, path: Path, *, max_runs: int, window_seconds: int) -> None:
        self.path = path
        self.max_runs = max_runs
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.records = self._load_records()

    def _load_records(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("records") if isinstance(payload, dict) else {}
        return records if isinstance(records, dict) else {}

    def _save_records_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "maxRuns": self.max_runs,
            "windowSeconds": self.window_seconds,
            "records": self.records,
        }
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def _hash_ip(self, client_ip: str) -> str:
        return hash_client_ip(client_ip)

    def _prune_expired_locked(self, now: float) -> bool:
        stale_keys = [
            key
            for key, record in self.records.items()
            if now >= float(record.get("reset_at") or 0)
        ]
        if not stale_keys:
            return False
        for key in stale_keys:
            self.records.pop(key, None)
        return True

    def _status_from_record(self, record: Dict[str, Any] | None, now: float) -> Dict[str, Any]:
        used = int(record.get("used") or 0) if record else 0
        reset_at = float(record.get("reset_at") or 0) if record else 0
        if not record or now >= reset_at:
            used = 0
            reset_at = 0
        remaining = max(0, self.max_runs - used)
        reset_in_seconds = max(0, int(math.ceil(reset_at - now))) if reset_at else None
        return {
            "limit": self.max_runs,
            "used": used,
            "remaining": remaining,
            "windowSeconds": self.window_seconds,
            "resetAtMs": int(reset_at * 1000) if reset_at else None,
            "resetInSeconds": reset_in_seconds,
            "exhausted": remaining <= 0,
            "message": self._build_message(remaining, used, reset_in_seconds),
        }

    def _build_message(self, remaining: int, used: int, reset_in_seconds: int | None) -> str:
        if remaining > 0:
            return f"{remaining}/{self.max_runs} runs remaining in the current 24-hour window."
        if reset_in_seconds:
            hours, remainder = divmod(reset_in_seconds, 3600)
            minutes = remainder // 60
            if hours:
                return f"Daily run limit reached for this IP ({used}/{self.max_runs}). Try again in {hours}h {minutes}m."
            return f"Daily run limit reached for this IP ({used}/{self.max_runs}). Try again in {max(1, minutes)}m."
        return f"Daily run limit reached for this IP ({used}/{self.max_runs})."

    def snapshot(self, client_ip: str) -> Dict[str, Any]:
        now = time.time()
        key = self._hash_ip(client_ip)
        with self.lock:
            if self._prune_expired_locked(now):
                self._save_records_locked()
            return self._status_from_record(self.records.get(key), now)

    def consume(self, client_ip: str) -> Dict[str, Any]:
        now = time.time()
        key = self._hash_ip(client_ip)
        with self.lock:
            mutated = self._prune_expired_locked(now)
            record = self.records.get(key)
            if not record or now >= float(record.get("reset_at") or 0):
                record = {
                    "used": 0,
                    "window_started_at": now,
                    "reset_at": now + self.window_seconds,
                }
                self.records[key] = record
                mutated = True

            status = self._status_from_record(record, now)
            if status["remaining"] <= 0:
                if mutated:
                    self._save_records_locked()
                raise RunQuotaExceeded(status)

            record["used"] = int(record.get("used") or 0) + 1
            record["last_used_at"] = now
            self.records[key] = record
            self._save_records_locked()
            return self._status_from_record(record, now)


class RedisRunQuotaStore(RunQuotaStore):
    CONSUME_SCRIPT = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1]) * 1000
local max_runs = tonumber(ARGV[2])
local current = redis.call('GET', key)
if not current then
  redis.call('SET', key, 1, 'PX', window_ms, 'NX')
  return {1, redis.call('PTTL', key), 0}
end

current = tonumber(current)
local ttl = redis.call('PTTL', key)
if ttl < 0 then
  redis.call('PEXPIRE', key, window_ms)
  ttl = redis.call('PTTL', key)
end

if current >= max_runs then
  return {current, ttl, 1}
end

local used = redis.call('INCR', key)
ttl = redis.call('PTTL', key)
if ttl < 0 then
  redis.call('PEXPIRE', key, window_ms)
  ttl = redis.call('PTTL', key)
end
return {used, ttl, 0}
""".strip()

    def __init__(self, redis_url: str, *, max_runs: int, window_seconds: int, key_prefix: str) -> None:
        if redis_lib is None:
            raise RuntimeError("redis-py is required for Redis-backed run quotas. Add the 'redis' package to the image.")
        self.path = RUN_QUOTA_STORE_PATH
        self.max_runs = max_runs
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.records: Dict[str, Dict[str, Any]] = {}
        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":")
        self.client = redis_lib.Redis.from_url(
            redis_url,
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self.consume_script = self.client.register_script(self.CONSUME_SCRIPT)

    def _key(self, client_ip: str) -> str:
        return f"{self.key_prefix}:{self._hash_ip(client_ip)}"

    def _record_from_usage(self, used: int, ttl_ms: int | None, now: float) -> Dict[str, Any] | None:
        if used <= 0:
            return None
        ttl_ms = int(ttl_ms or 0)
        if ttl_ms <= 0:
            return {"used": used, "reset_at": now + self.window_seconds}
        return {
            "used": used,
            "reset_at": now + ttl_ms / 1000.0,
        }

    def snapshot(self, client_ip: str) -> Dict[str, Any]:
        now = time.time()
        key = self._key(client_ip)
        value, ttl_ms = self.client.pipeline().get(key).pttl(key).execute()
        used = int(value or 0)
        if used and int(ttl_ms or 0) < 0:
            self.client.pexpire(key, self.window_seconds * 1000)
            ttl_ms = self.client.pttl(key)
        return self._status_from_record(self._record_from_usage(used, ttl_ms, now), now)

    def consume(self, client_ip: str) -> Dict[str, Any]:
        now = time.time()
        key = self._key(client_ip)
        used, ttl_ms, exhausted = self.consume_script(
            keys=[key],
            args=[self.window_seconds, self.max_runs],
        )
        status = self._status_from_record(self._record_from_usage(int(used or 0), int(ttl_ms or 0), now), now)
        if int(exhausted or 0):
            raise RunQuotaExceeded(status)
        return status


def build_run_quota_store() -> RunQuotaStore:
    if RUN_QUOTA_REDIS_URL:
        return RedisRunQuotaStore(
            RUN_QUOTA_REDIS_URL,
            max_runs=RUN_QUOTA_MAX_RUNS,
            window_seconds=RUN_QUOTA_WINDOW_SECONDS,
            key_prefix=RUN_QUOTA_REDIS_KEY_PREFIX,
        )
    return RunQuotaStore(
        RUN_QUOTA_STORE_PATH,
        max_runs=RUN_QUOTA_MAX_RUNS,
        window_seconds=RUN_QUOTA_WINDOW_SECONDS,
    )


def extract_trusted_client_ip(raw_value: str, *, prefer_last: bool = False) -> str | None:
    if not raw_value:
        return None

    candidates = [part.strip() for part in raw_value.split(",")]
    if prefer_last:
        candidates = list(reversed(candidates))

    for candidate in candidates:
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered == "unknown":
            continue
        if lowered.startswith("for="):
            candidate = candidate[4:].strip()
        candidate = candidate.strip().strip('"').strip("'").strip("[]")
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def normalize_required_text(value: Any, field_label: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_label} is required.")
    if len(text) > max_chars:
        raise ValueError(f"{field_label} exceeds the {max_chars}-character limit.")
    return text


def normalize_optional_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


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
    prefer_standard_request: bool = False


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
    "doubao2lite": ModelConfig(
        model_id="doubao2lite",
        company="Doubao",
        provider="ByteDance",
        family="Doubao",
        label="Doubao Seed 2.0 Lite",
        api_model="volcengine/doubao-seed-2-0-lite",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=0.6,
        output_price_yuan_per_million=3.6,
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
    "kimi26": ModelConfig(
        model_id="kimi26",
        company="Kimi",
        provider="Moonshot",
        family="Kimi",
        label="Kimi K2.6",
        api_model="moonshot/moonshotai/kimi-k2.6",
        prompt_template=PROMPT_SHORT,
        input_price_yuan_per_million=6.5,
        output_price_yuan_per_million=27.0,
        supports_reasoning_trace=True,
        max_tokens=30000,
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
        provider="ppinfra",
        family="Claude",
        label="Claude Opus 4.6",
        api_model="ppinfra/claude-opus-4.6",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=36.5,
        output_price_yuan_per_million=273.75,
        supports_reasoning_trace=True,
        extra_body=CLAUDE_THINKING_EXTRA_BODY,
        temperature_override=1.0,
    ),
    "claudeopus47": ModelConfig(
        model_id="claudeopus47",
        company="Claude",
        provider="Anthropic",
        family="Claude",
        label="Claude Opus 4.7",
        api_model="anthropic/claude-opus-4.7",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=35.0,
        output_price_yuan_per_million=175.0,
        supports_reasoning_trace=True,
        temperature_override=1.0,
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
        supports_reasoning_trace=True,
        extra_body=CLAUDE_ADAPTIVE_THINKING_EXTRA_BODY,
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
        supports_reasoning_trace=True,
        extra_body=CLAUDE_THINKING_EXTRA_BODY,
        temperature_override=1.0,
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
        prefer_standard_request=True,
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
        provider="Qiniu",
        family="Gemini",
        label="Gemini 3.1 Pro Preview",
        api_model="qiniu/gemini-3.1-pro-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=14.6,
        output_price_yuan_per_million=87.6,
        supports_reasoning_trace=True,
    ),
    "gemini3pro": ModelConfig(
        model_id="gemini3pro",
        company="Gemini",
        provider="Google",
        family="Gemini",
        label="Gemini 3 Pro Preview",
        api_model="google/gemini-3-pro-preview",
        prompt_template=PROMPT_TRYTO,
        input_price_yuan_per_million=10.22,
        output_price_yuan_per_million=61.32,
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

VERIFIER_MODEL_OPTIONS: Dict[str, Dict[str, str]] = {
    "gpt5mini": {
        "id": "gpt5mini",
        "label": "GPT-5 Mini",
        "api_model": "openai/gpt-5-mini",
    },
    "oss": {
        "id": "oss",
        "label": "GPT-120B",
        "api_model": "qiniu/gpt-oss-120b",
    },
    "oss20": {
        "id": "oss20",
        "label": "GPT-20B",
        "api_model": "qiniu/gpt-oss-20b",
    },
    "grok4fast": {
        "id": "grok4fast",
        "label": "Grok-4 Fast",
        "api_model": "qiniu/grok-4-fast",
    },
}
DEFAULT_VERIFIER_OPTION_ID = "gpt5mini"


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
    if not archived_by_model:
        return {
            "direct": {"verification": "UNKNOWN"},
            "trs": {
                "verification": "UNKNOWN",
                "skill_text": NO_EXPERIENCE_SKILL_TEXT,
                "skill_score": 0.0,
            },
        }

    if model_id in archived_by_model:
        return archived_by_model[model_id]

    target_family = MODEL_CONFIGS[model_id].family
    for fallback_model_id, fallback_config in MODEL_CONFIGS.items():
        if fallback_model_id in archived_by_model and fallback_config.family == target_family:
            return archived_by_model[fallback_model_id]

    for fallback_model_id in ARCHIVED_FALLBACK_PRIORITY:
        if fallback_model_id in archived_by_model:
            return archived_by_model[fallback_model_id]

    return next(iter(archived_by_model.values()))


def load_benchmark_example_groups() -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    if not BENCHMARK_GROUPS_PATH.exists():
        return [], []

    with BENCHMARK_GROUPS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    benchmark_accuracy: dict[str, Any] = {}
    benchmark_accuracy_model_label = "Doubao 1.8"
    benchmark_accuracy_model_id = "doubao1.8"
    if BENCHMARK_DIRECT_ACCURACY_PATH.exists():
        with BENCHMARK_DIRECT_ACCURACY_PATH.open("r", encoding="utf-8") as handle:
            accuracy_payload = json.load(handle)
        benchmark_accuracy = (accuracy_payload.get("byQuestionId") or {})
        benchmark_accuracy_model_label = str(accuracy_payload.get("modelLabel") or benchmark_accuracy_model_label)
        benchmark_accuracy_model_id = str(accuracy_payload.get("modelId") or benchmark_accuracy_model_id)

    groups: list[Dict[str, Any]] = []
    examples: list[Dict[str, Any]] = []
    for raw_group in payload.get("groups", []):
        option_ids: list[str] = []
        options_payload: list[Dict[str, Any]] = []
        for option in raw_group.get("options", []):
            example = {
                "id": option["id"],
                "questionId": option.get("questionId") or "",
                "title": option["title"],
                "subtitle": option.get("subtitle") or raw_group.get("label") or "",
                "highlight": "Live benchmark example with runtime skill retrieval.",
                "question": option.get("question") or "",
                "answer": option.get("answer") or "",
                "topic": option.get("topic") or raw_group.get("label") or "Benchmark",
                "difficulty": option.get("difficulty") or "Benchmark",
                "benchmark": option.get("benchmark") or "",
                "benchmarkDirectStats": {
                    **deepcopy(benchmark_accuracy.get(option.get("questionId") or "") or {}),
                    "modelLabel": benchmark_accuracy_model_label,
                    "modelId": benchmark_accuracy_model_id,
                }
                if benchmark_accuracy.get(option.get("questionId") or "")
                else None,
                "archived": {
                    model_id: deepcopy(resolve_archived_example_for_model({}, model_id))
                    for model_id in MODEL_CONFIGS
                },
            }
            examples.append(example)
            option_ids.append(example["id"])
            options_payload.append(
                {
                    "id": example["id"],
                    "label": option.get("optionLabel") or example["title"],
                    "title": example["title"],
                }
            )

        groups.append(
            {
                "id": raw_group.get("id") or f"group::{raw_group.get('label', 'benchmark')}",
                "label": raw_group.get("label") or "Benchmark",
                "subtitle": raw_group.get("subtitle") or "",
                "kind": raw_group.get("kind") or "benchmark",
                "optionIds": option_ids,
                "options": options_payload,
            }
        )

    return groups, examples


def load_examples_payload() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Missing checked-in demo data file at {DATA_PATH}."
        )
    with DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    deepmath_examples = payload.get("examples", [])
    if deepmath_examples:
        preferred_order = {
            "random-walk-bound": -100,
            "bisector-angle": 100,
        }
        payload["examples"] = sorted(
            deepmath_examples,
            key=lambda example: (
                preferred_order.get(example.get("id", ""), 0),
                deepmath_examples.index(example),
            ),
        )

    groups: list[Dict[str, Any]] = []
    for example in payload.get("examples", []):
        archived_by_model = example.get("archived", {})
        example["archived"] = {
            model_id: deepcopy(resolve_archived_example_for_model(archived_by_model, model_id))
            for model_id in MODEL_CONFIGS
        }
    if payload.get("examples"):
        groups.append(
            {
                "id": "group::deepmath-curated",
                "label": "DeepMath Curated",
                "subtitle": f"{len(payload['examples'])} demo problems",
                "kind": "deepmath",
                "optionIds": [example["id"] for example in payload["examples"]],
                "options": [
                    {
                        "id": example["id"],
                        "label": example["title"],
                        "title": example["title"],
                    }
                    for example in payload["examples"]
                ],
            }
        )

    benchmark_groups, benchmark_examples = load_benchmark_example_groups()
    payload["examples"].extend(benchmark_examples)
    groups.extend(benchmark_groups)
    payload["exampleGroups"] = groups

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
            "prefersStandardRequest": config.prefer_standard_request,
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
    verifier_option_id = default_verifier_option_id()
    verifier_option = VERIFIER_MODEL_OPTIONS[verifier_option_id]
    payload["verifier"] = {
        "defaultId": verifier_option_id,
        "label": verifier_option["label"],
        "model": verifier_option["api_model"],
        "options": [verifier_option_payload(option) for option in VERIFIER_MODEL_OPTIONS.values()],
        "promptStyle": "Original DeepMath answer-checker prompt",
    }
    return payload


def load_precomputed_example_previews(examples_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not EXAMPLE_PREVIEW_MAP_PATH.exists():
        return {}

    with EXAMPLE_PREVIEW_MAP_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    previews = payload.get("previews") or {}
    filtered: Dict[str, Any] = {}
    for cache_key, preview in previews.items():
        example_id = cache_key.split("@@", 1)[0]
        example = examples_by_id.get(example_id)
        if example is None:
            continue
        canonicalized = dict(preview)
        canonicalized.update(
            {
                "id": example["id"],
                "questionId": example.get("questionId") or "",
                "title": example.get("title") or canonicalized.get("title") or "",
                "subtitle": example.get("subtitle") or canonicalized.get("subtitle") or "",
                "highlight": canonicalized.get("highlight") or example.get("highlight") or "",
                "question": example.get("question") or canonicalized.get("question") or "",
                "answer": example.get("answer") or canonicalized.get("answer") or "",
                "topic": example.get("topic") or canonicalized.get("topic") or "",
                "difficulty": example.get("difficulty") or canonicalized.get("difficulty") or "",
                "benchmarkDirectStats": deepcopy(example.get("benchmarkDirectStats")) or None,
                "sourceMode": "example",
            }
        )
        filtered[cache_key] = canonicalized
    return filtered


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


def normalize_answer_text(text: str) -> str:
    return "".join(char for char in (text or "").lower() if char.isalnum())


def open_jsonl_handle(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_skill_dataset_records(dataset_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    records: list[Dict[str, Any]] = []
    candidates = ()
    fallback_label = dataset_id
    if dataset_id == "deepmath":
        candidates = DEEPMATH_SKILL_CORPUS_CANDIDATES
        fallback_label = "DeepMath-103K"
    elif dataset_id == "aops":
        candidates = AOPS_SKILL_CORPUS_CANDIDATES
        fallback_label = "AoPS"
    else:
        raise ValueError(f"Unsupported skill dataset: {dataset_id}")

    for candidate in candidates:
        path = candidate["path"]
        if not path.exists():
            continue

        records = []
        source_label = candidate.get("label") or candidate.get("source_label") or fallback_label
        with open_jsonl_handle(path) as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if candidate["format"] == "deployable":
                    source_key = (item.get("source_key") or "").strip()
                    item_label = (item.get("source_label") or source_label_for_key(source_key)).strip()
                    effective_label = candidate.get("label") or item_label or fallback_label
                    records.append(
                        {
                            "question_id": item.get("question_id") or "",
                            "question": (item.get("question") or "").strip(),
                            "answer": (item.get("answer") or "").strip(),
                            "topic": (item.get("topic") or "").strip(),
                            "difficulty": item.get("difficulty"),
                            "skill_text": (item.get("skill_text") or "").strip(),
                            "keywords": (item.get("keywords") or "").strip(),
                            "skill_score": float(item.get("skill_score") or 0.0),
                            "source_key": source_key,
                            "source_label": effective_label,
                        }
                    )
                    continue

                if candidate["format"] == "aops":
                    records.append(
                        {
                            "question_id": item.get("question_id") or "",
                            "question": (item.get("question") or "").strip(),
                            "answer": (item.get("answer") or "").strip(),
                            "topic": (item.get("topic") or "").strip(),
                            "difficulty": item.get("difficulty"),
                            "skill_text": (item.get("heuristic") or item.get("skill_text") or "").strip(),
                            "keywords": (item.get("keywords") or "").strip(),
                            "skill_score": float(item.get("skill_score") or 0.0),
                            "source_key": candidate["source_key"],
                            "source_label": candidate["source_label"],
                        }
                    )
                    continue

                records.append(
                    {
                        "question_id": item.get("question_id") or "",
                        "question": (item.get("question") or "").strip(),
                        "answer": (item.get("answer") or "").strip(),
                        "topic": (item.get("topic") or "").strip(),
                        "difficulty": item.get("difficulty"),
                        "skill_text": (item.get("heuristic") or "").strip(),
                        "keywords": (item.get("keywords") or "").strip(),
                        "skill_score": float(item.get("heuristic_score") or 0.0),
                        "source_key": candidate["source_key"],
                        "source_label": candidate["source_label"],
                    }
                )
        if records:
            return {
                "dataset_id": dataset_id,
                "records": records,
                "label": source_label,
                "path": str(path),
            }

    if dataset_id == "deepmath":
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
                    records.append(
                        {
                            "question_id": item.get("question_id") or "",
                            "question": (item.get("question") or "").strip(),
                            "answer": (item.get("answer") or "").strip(),
                            "topic": (item.get("topic") or "").strip(),
                            "difficulty": item.get("difficulty"),
                            "skill_text": (item.get("heuristic_used") or "").strip(),
                            "keywords": (item.get("keywords") or "").strip(),
                            "skill_score": float(item.get("heuristic_score") or 0.0),
                            "source_key": source_key,
                            "source_label": source_label_for_key(source_key),
                        }
                    )

    return {
        "dataset_id": dataset_id,
        "records": records,
        "label": fallback_label,
        "path": None,
    }


def build_skill_corpus(payload: Dict[str, Any], dataset_id: str) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []
    doc_freq: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str]] = set()
    corpus_source = iter_skill_dataset_records(dataset_id, payload)

    for item in corpus_source["records"]:
        question = item["question"]
        skill_text = item["skill_text"]
        if not question or not skill_text:
            continue

        dedupe_key = (question, skill_text)
        if dedupe_key in seen_pairs:
            continue
        seen_pairs.add(dedupe_key)

        question_token_set = set(tokenize_retrieval_text(question))
        answer_token_set = set(tokenize_retrieval_text(item["answer"]))
        topic_token_set = set(tokenize_retrieval_text(item.get("topic") or ""))
        keyword_token_set = set(tokenize_retrieval_text(item.get("keywords") or ""))
        retrieval_token_set = question_token_set | answer_token_set | topic_token_set | keyword_token_set
        if not retrieval_token_set:
            continue

        doc_freq.update(retrieval_token_set)
        entries.append(
            {
                **item,
                "question_token_set": question_token_set,
                "answer_token_set": answer_token_set,
                "topic_token_set": topic_token_set,
                "keyword_token_set": keyword_token_set,
                "retrieval_token_set": retrieval_token_set,
                "normalized_answer": normalize_answer_text(item["answer"]),
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
        "dataset_id": dataset_id,
        "label": corpus_source["label"],
        "path": corpus_source["path"],
    }


def build_skill_corpora(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    corpora: Dict[str, Dict[str, Any]] = {}
    for option in SKILL_DATASET_OPTIONS:
        corpora[option["id"]] = build_skill_corpus(payload, option["id"])
    return corpora


def resolve_skill_dataset_ids(
    requested_dataset_ids: Any,
    corpora: Dict[str, Dict[str, Any]],
) -> list[str]:
    available_ids = [option["id"] for option in SKILL_DATASET_OPTIONS if option["id"] in corpora]
    if not available_ids:
        return []

    requested: list[str] = []
    if isinstance(requested_dataset_ids, (list, tuple, set)):
        requested = [str(item).strip() for item in requested_dataset_ids if str(item).strip()]
    elif requested_dataset_ids:
        requested = [str(requested_dataset_ids).strip()]

    if not requested:
        requested = [dataset_id for dataset_id in DEFAULT_SELECTED_SKILL_DATASET_IDS if dataset_id in available_ids]
    if not requested:
        requested = available_ids[:1]

    normalized: list[str] = []
    for dataset_id in requested:
        if dataset_id in available_ids and dataset_id not in normalized:
            normalized.append(dataset_id)
    if not normalized:
        raise ValueError("Select at least one skill dataset.")
    return normalized


def retrieve_skill_entry(
    question: str,
    reference_answer: str,
    corpora: Dict[str, Dict[str, Any]],
    dataset_ids: list[str],
) -> Dict[str, Any]:
    query = (question or "").strip()
    if not query:
        raise ValueError("Custom mode requires a non-empty question.")

    question_tokens = set(tokenize_retrieval_text(query))
    answer_tokens = set(tokenize_retrieval_text(reference_answer))
    normalized_answer = normalize_answer_text(reference_answer)
    if not question_tokens and not answer_tokens:
        raise ValueError("The custom question is too short to retrieve a skill card.")

    best_entry: Dict[str, Any] | None = None
    best_score = float("-inf")
    best_overlap: set[str] = set()
    selected_labels: list[str] = []

    for dataset_id in dataset_ids:
        corpus = corpora.get(dataset_id)
        if not corpus:
            continue
        selected_labels.append(corpus["label"])
        entries = corpus.get("entries", [])
        for entry in entries:
            question_overlap = question_tokens & entry["question_token_set"]
            topic_overlap = question_tokens & entry["topic_token_set"]
            keyword_overlap = question_tokens & entry["keyword_token_set"]
            answer_overlap = answer_tokens & entry["answer_token_set"]
            exact_answer_match = bool(normalized_answer) and normalized_answer == entry["normalized_answer"]
            overlap = question_overlap | topic_overlap | keyword_overlap | answer_overlap
            if not overlap and not exact_answer_match:
                continue

            question_score = sum(corpus["idf"].get(token, 1.0) for token in question_overlap)
            topic_score = 0.55 * sum(corpus["idf"].get(token, 1.0) for token in topic_overlap)
            keyword_score = 0.85 * sum(corpus["idf"].get(token, 1.0) for token in keyword_overlap)
            answer_score = 1.1 * sum(corpus["idf"].get(token, 1.0) for token in answer_overlap)
            question_like_overlap = question_overlap | topic_overlap | keyword_overlap
            coverage = len(question_like_overlap) / max(1, len(question_tokens)) if question_tokens else 0.0
            answer_coverage = len(answer_overlap) / max(1, len(answer_tokens)) if answer_tokens else 0.0
            density = len(overlap) / max(1, len(entry["retrieval_token_set"]))
            score = (
                (question_score + topic_score + keyword_score) * (0.76 + 0.24 * coverage)
                + answer_score * (1.05 + 0.35 * answer_coverage)
                + density
                + entry["skill_score"] * 0.004
            )
            if exact_answer_match:
                score += 2.5
            if score > best_score:
                best_score = score
                best_entry = {
                    **entry,
                    "dataset_id": dataset_id,
                    "dataset_label": corpus["label"],
                }
                best_overlap = overlap

    if best_entry is None:
        source_label = " + ".join(selected_labels) if selected_labels else "selected skill datasets"
        return {
            "question_id": "",
            "question": "",
            "answer": "",
            "topic": "",
            "difficulty": None,
            "skill_text": NO_EXPERIENCE_SKILL_TEXT,
            "skill_score": 0.0,
            "source_key": "no_experience",
            "source_label": source_label,
            "dataset_id": "none",
            "dataset_label": source_label,
            "retrieval_score": 0.0,
            "matched_tokens": [],
            "no_experience": True,
        }

    return {
        **best_entry,
        "retrieval_score": round(best_score, 4),
        "matched_tokens": sorted(best_overlap),
        "no_experience": False,
    }


def summarize_custom_question(question: str, limit: int = 76) -> str:
    first_line = next((line.strip() for line in question.splitlines() if line.strip()), "").strip()
    if not first_line:
        return "Custom Problem"
    if len(first_line) <= limit:
        return first_line
    return first_line[: limit - 1].rstrip() + "…"


def build_preview_example(base_context: Dict[str, Any], retrieval: Dict[str, Any]) -> Dict[str, Any]:
    question = (base_context.get("question") or "").strip()
    reference_answer = (base_context.get("answer") or base_context.get("referenceAnswer") or "").strip()
    source_mode = (base_context.get("sourceMode") or "custom").strip() or "custom"
    if source_mode == "custom":
        display_title = summarize_custom_question(question)
        subtitle = (
            f"No matching skill card found in {retrieval['source_label']}."
            if retrieval.get("no_experience")
            else f"Matched to {retrieval['source_label']}"
            + (f" · {retrieval['topic']}" if retrieval.get("topic") else "")
        )
        highlight = (
            "No lexical match found. TRS will run without retrieved experience."
            if retrieval.get("no_experience")
            else "Skill card retrieved from the selected skill datasets using lexical overlap."
        )
    else:
        display_title = (base_context.get("title") or "Curated Example").strip()
        subtitle = (base_context.get("subtitle") or "").strip()
        highlight = (
            "No matching skill card found in the selected skill datasets."
            if retrieval.get("no_experience")
            else f"Retrieved from {retrieval['source_label']}."
        )

    archived_template = {
        "direct": {"verification": "UNKNOWN"},
        "trs": {
            "verification": "UNKNOWN",
            "skill_text": retrieval["skill_text"],
            "skill_score": retrieval["skill_score"],
        },
    }
    return {
        "id": (base_context.get("id") or "custom-problem").strip() or "custom-problem",
        "questionId": (base_context.get("questionId") or "").strip(),
        "title": display_title,
        "subtitle": subtitle,
        "highlight": highlight,
        "question": question,
        "answer": reference_answer,
        "topic": base_context.get("topic") or ("Custom Input" if source_mode == "custom" else ""),
        "difficulty": base_context.get("difficulty") or ("User" if source_mode == "custom" else ""),
        "sourceMode": source_mode,
        "benchmarkDirectStats": deepcopy(base_context.get("benchmarkDirectStats")) or None,
        "archived": {
            model_id: deepcopy(archived_template)
            for model_id in MODEL_CONFIGS
        },
        "retrieval": {
            "datasetId": retrieval.get("dataset_id") or "",
            "datasetLabel": retrieval.get("dataset_label") or retrieval["source_label"],
            "sourceLabel": retrieval["source_label"],
            "matchedQuestion": retrieval["question"],
            "matchedTopic": retrieval.get("topic") or "",
            "matchedDifficulty": retrieval.get("difficulty"),
            "matchedTokens": retrieval.get("matched_tokens") or [],
            "score": retrieval["retrieval_score"],
            "noExperience": bool(retrieval.get("no_experience")),
        },
        "skillText": retrieval["skill_text"],
        "skillScore": retrieval["skill_score"],
    }


def serialize_preview(example: Dict[str, Any]) -> Dict[str, Any]:
    first_archived = next(iter(example["archived"].values()))
    return {
        "id": example["id"],
        "questionId": example.get("questionId") or "",
        "title": example["title"],
        "subtitle": example["subtitle"],
        "question": example["question"],
        "answer": example["answer"],
        "topic": example["topic"],
        "difficulty": example["difficulty"],
        "skillText": first_archived["trs"]["skill_text"],
        "skillScore": first_archived["trs"]["skill_score"],
        "retrieval": example["retrieval"],
        "benchmarkDirectStats": deepcopy(example.get("benchmarkDirectStats")) or None,
        "highlight": example.get("highlight") or "",
        "sourceMode": example.get("sourceMode") or "custom",
    }


def compute_cost_yuan(prompt_tokens: int, completion_tokens: int, config: ModelConfig) -> float:
    return (
        prompt_tokens / 1_000_000 * config.input_price_yuan_per_million
        + completion_tokens / 1_000_000 * config.output_price_yuan_per_million
    )


def build_prompt(template: str, question: str, skill_text: str) -> str:
    effective_skill_text = ""
    if skill_text.strip() and skill_text.strip() != NO_EXPERIENCE_SKILL_TEXT:
        effective_skill_text = skill_text
    return template.replace("{SOLVING_HINTS}", effective_skill_text).replace("{PROBLEM}", question)


def build_direct_prompt(question: str) -> str:
    return PROMPT_DIRECT.replace("{PROBLEM}", question)


def get_api_key() -> str:
    return os.environ.get("TRS_DEMO_API_KEY") or os.environ.get("REBUTTAL_API_KEY", "")


def get_verify_model() -> str:
    return os.environ.get("TRS_DEMO_VERIFY_MODEL", "openai/gpt-5-mini").strip() or "openai/gpt-5-mini"


def verifier_option_payload(option: Dict[str, str]) -> Dict[str, str]:
    return {
        "id": option["id"],
        "label": option["label"],
        "apiModel": option["api_model"],
    }


def default_verifier_option_id() -> str:
    configured_model = get_verify_model()
    for option_id, option in VERIFIER_MODEL_OPTIONS.items():
        if option["api_model"] == configured_model:
            return option_id
    return DEFAULT_VERIFIER_OPTION_ID


def resolve_verifier_model(verifier_model_id: str | None) -> str:
    option_id = (verifier_model_id or "").strip()
    if option_id:
        option = VERIFIER_MODEL_OPTIONS.get(option_id)
        if not option:
            raise ValueError(f"Unsupported verifierModelId: {option_id}")
        return option["api_model"]
    return get_verify_model()


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
    normalized = (content or "").strip()
    if not normalized:
        return "UNKNOWN"

    upper = normalized.upper()
    exact = re.fullmatch(r"[\s\"'`*\-:]*?(CORRECT|INCORRECT)[\s\"'`*.:!?\-]*", upper)
    if exact:
        return exact.group(1)

    verdict_patterns = [
        r"\bFINAL(?:\s+VERDICT)?\s*[:：-]?\s*(CORRECT|INCORRECT)\b",
        r"\bVERDICT\s*[:：-]?\s*(CORRECT|INCORRECT)\b",
        r"\bRESULT\s*[:：-]?\s*(CORRECT|INCORRECT)\b",
        r"\bANSWER\s*[:：-]?\s*(CORRECT|INCORRECT)\b",
    ]
    for pattern in verdict_patterns:
        match = re.search(pattern, upper)
        if match:
            return match.group(1)

    tokens = re.findall(r"\b(?:CORRECT|INCORRECT)\b", upper)
    if len(tokens) == 1:
        return tokens[0]
    if "INCORRECT" in tokens:
        return "INCORRECT"
    if "CORRECT" in tokens:
        return "CORRECT"

    semantic_patterns = [
        (r"\bDO(?:ES)?\s+NOT\s+MATCH\b", "INCORRECT"),
        (r"\bNOT\s+EQUIVALENT\b", "INCORRECT"),
        (r"\bMATCH(?:ES)?\b", "CORRECT"),
        (r"\bEQUIVALENT\b", "CORRECT"),
    ]
    for pattern, verdict in semantic_patterns:
        if re.search(pattern, upper):
            return verdict

    first_nonempty_line = next((line.strip() for line in normalized.splitlines() if line.strip()), "")
    return first_nonempty_line.upper() or "UNKNOWN"


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


def verifier_max_tokens_limit(model_name: str) -> int:
    lowered = model_name.lower()
    if "gpt-5" in lowered or "openai/" in lowered:
        return 32
    if "gpt-oss" in lowered or "grok" in lowered or "qiniu/" in lowered:
        return 96
    return 64


def verify_answer(
    question_text: str,
    reference_answer: str,
    candidate_answer: str,
    verifier_model: str | None = None,
) -> Dict[str, Any]:
    verifier_model = (verifier_model or "").strip() or get_verify_model()
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
    payload[verifier_max_tokens_param(verifier_model)] = verifier_max_tokens_limit(verifier_model)

    opener = build_opener()
    timeout_seconds = get_verify_timeout_seconds()
    parsed = None
    last_error = ""
    content = ""
    for attempt in range(1, max_retries + 1):
        try:
            with opener.open(build_json_api_request(payload), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            choices = parsed.get("choices", [])
            message = choices[0].get("message", {}) if choices else {}
            content = extract_content_text(message.get("content", "")).strip()
            if not content:
                content = extract_reasoning_text(message).strip()
            if content:
                break
            last_error = "Verifier returned an empty response."
            if attempt >= max_retries:
                return {
                    "status": "unknown",
                    "label": "Verifier Empty",
                    "reference_answer": reference_answer,
                    "verifier_model": verifier_model,
                    "verdict": "UNKNOWN",
                    "verifier_response": "",
                }
            time.sleep(retry_sleep_seconds(attempt, base=0.4, cap=3.0))
            continue
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
    verifier_model: str,
    cancel_event: threading.Event | None = None,
) -> Dict[str, Any]:
    prompt_tokens = parse_usage_int(usage.get("prompt_tokens"))
    completion_tokens = parse_usage_int(usage.get("completion_tokens"))
    total_tokens = parse_usage_int(usage.get("total_tokens"))
    completion_details = usage.get("completion_tokens_details", {}) if isinstance(usage.get("completion_tokens_details"), dict) else {}
    reasoning_tokens = parse_usage_int(completion_details.get("reasoning_tokens"))
    visible_completion_tokens = None
    if completion_tokens is not None and reasoning_tokens is not None:
        visible_completion_tokens = max(0, completion_tokens - reasoning_tokens)
    cost_yuan = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_yuan = round(compute_cost_yuan(prompt_tokens, completion_tokens, config), 6)

    if cancel_event and cancel_event.is_set():
        correctness = {
            "status": "cancelled",
            "label": "Cancelled",
            "reference_answer": reference_answer,
            "verifier_model": verifier_model,
            "verdict": "CANCELLED",
            "verifier_response": "",
        }
    else:
        correctness = verify_answer(question_text, reference_answer, answer_text, verifier_model=verifier_model)
    stop_info = summarize_stop_reason(finish_reason, "\n".join([reasoning_text or "", answer_text or ""]))

    return {
        "reasoning_text": reasoning_text or "",
        "answer_text": answer_text or "",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "visible_completion_tokens": visible_completion_tokens,
        "total_tokens": total_tokens,
        "cost_yuan": cost_yuan,
        "correctness": correctness,
        "finish_reason": stop_info["finish_reason"],
        "stop_label": stop_info["stop_label"],
        "stop_warning": stop_info["stop_warning"],
        "truncated": stop_info["truncated"],
        "possible_repetition": stop_info["possible_repetition"],
    }


def extract_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.append(extract_content_text(item))
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            if key in value:
                return extract_content_text(value[key])
    return ""


def merge_reasoning_segments(*segments: str) -> str:
    merged = ""
    for segment in segments:
        candidate = (segment or "").strip()
        if not candidate:
            continue
        if not merged:
            merged = candidate
            continue
        if candidate in merged:
            continue
        if merged in candidate:
            merged = candidate
            continue
        merged = f"{merged}\n\n{candidate}"
    return merged


def split_think_tagged_text(
    text: str,
    *,
    initial_inside_think: bool = False,
    assume_reasoning_prefix: bool = False,
) -> tuple[str, str, bool, bool]:
    if not text:
        return "", "", initial_inside_think, False

    reasoning_parts: list[str] = []
    answer_parts: list[str] = []
    inside_think = initial_inside_think
    saw_tag = False
    cursor = 0
    lowered = text.lower()

    if assume_reasoning_prefix and not inside_think:
        close_idx = lowered.find(THINK_CLOSE_TAG)
        open_idx = lowered.find(THINK_OPEN_TAG)
        if close_idx != -1 and (open_idx == -1 or close_idx < open_idx):
            reasoning_parts.append(text[:close_idx])
            cursor = close_idx + len(THINK_CLOSE_TAG)
            saw_tag = True

    while cursor < len(text):
        lowered = text.lower()
        open_idx = lowered.find(THINK_OPEN_TAG, cursor)
        close_idx = lowered.find(THINK_CLOSE_TAG, cursor)
        next_candidates = [idx for idx in (open_idx, close_idx) if idx != -1]
        if not next_candidates:
            segment = text[cursor:]
            if segment:
                (reasoning_parts if inside_think else answer_parts).append(segment)
            break

        next_idx = min(next_candidates)
        segment = text[cursor:next_idx]
        if segment:
            (reasoning_parts if inside_think else answer_parts).append(segment)

        if open_idx != -1 and next_idx == open_idx:
            inside_think = True
            cursor = open_idx + len(THINK_OPEN_TAG)
        else:
            inside_think = False
            cursor = close_idx + len(THINK_CLOSE_TAG)
        saw_tag = True

    return "".join(reasoning_parts), "".join(answer_parts), inside_think, saw_tag


def extract_message_text_parts(message: Dict[str, Any]) -> tuple[str, str]:
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []

    reasoning_value = message.get("reasoning_content")
    if reasoning_value not in (None, "", []):
        reasoning_text = extract_content_text(reasoning_value)
        if reasoning_text:
            reasoning_parts.append(reasoning_text)

    content = message.get("content", "")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                block_type = str(block.get("type") or "").lower()
                text = extract_content_text(block)
                if not text:
                    continue
                if block_type in {"reasoning", "thinking", "reasoning_text", "thinking_text"}:
                    reasoning_parts.append(text)
                    continue
            else:
                text = extract_content_text(block)
                if not text:
                    continue

            inline_reasoning, inline_answer, _inside_think, saw_tag = split_think_tagged_text(
                text,
                assume_reasoning_prefix=bool(reasoning_parts),
            )
            if saw_tag:
                if inline_reasoning:
                    reasoning_parts.append(inline_reasoning)
                if inline_answer:
                    answer_parts.append(inline_answer)
                continue
            answer_parts.append(text)
    else:
        text = extract_content_text(content)
        inline_reasoning, inline_answer, _inside_think, saw_tag = split_think_tagged_text(
            text,
            assume_reasoning_prefix=bool(reasoning_parts),
        )
        if saw_tag:
            if inline_reasoning:
                reasoning_parts.append(inline_reasoning)
            if inline_answer:
                answer_parts.append(inline_answer)
        elif text:
            answer_parts.append(text)

    return merge_reasoning_segments(*reasoning_parts), "".join(answer_parts)


def extract_reasoning_text(message: Dict[str, Any]) -> str:
    reasoning_text, _answer_text = extract_message_text_parts(message)
    return reasoning_text


def extract_answer_text(message: Dict[str, Any]) -> str:
    _reasoning_text, answer_text = extract_message_text_parts(message)
    return answer_text


def extract_stream_delta_parts(delta: Dict[str, Any], state: Dict[str, Any]) -> tuple[str, str]:
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []

    reasoning_value = delta.get("reasoning_content")
    if reasoning_value not in (None, "", []):
        reasoning_text = extract_content_text(reasoning_value)
        if reasoning_text:
            reasoning_parts.append(reasoning_text)
            state["saw_reasoning_signal"] = True

    content = delta.get("content", "")
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        if isinstance(block, dict):
            block_type = str(block.get("type") or "").lower()
            text = extract_content_text(block)
            if not text:
                continue
            if block_type in {"reasoning", "thinking", "reasoning_text", "thinking_text"}:
                reasoning_parts.append(text)
                state["saw_reasoning_signal"] = True
                continue
        else:
            text = extract_content_text(block)
            if not text:
                continue

        inline_reasoning, inline_answer, inside_think, saw_tag = split_think_tagged_text(
            text,
            initial_inside_think=bool(state.get("inside_think_tag")),
            assume_reasoning_prefix=bool(state.get("saw_reasoning_signal")) and not bool(state.get("saw_answer_content")),
        )
        state["inside_think_tag"] = inside_think
        if inline_reasoning:
            reasoning_parts.append(inline_reasoning)
            state["saw_reasoning_signal"] = True
        if inline_answer:
            answer_parts.append(inline_answer)
            state["saw_answer_content"] = True
        if not saw_tag and not inline_reasoning and not inline_answer and text:
            answer_parts.append(text)
            state["saw_answer_content"] = True

    return "".join(reasoning_parts), "".join(answer_parts)


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
    cost_reduction_pct = None
    if cost_saved is not None and direct["cost_yuan"] and direct["cost_yuan"] > 0:
        cost_reduction_pct = round(cost_saved / direct["cost_yuan"] * 100, 2)

    completion_reduction_pct = None
    if completion_saved is not None and direct["completion_tokens"] and direct["completion_tokens"] > 0:
        completion_reduction_pct = round(completion_saved / direct["completion_tokens"] * 100, 2)
    return {
        "completion_tokens_saved": completion_saved,
        "completion_reduction_pct": completion_reduction_pct,
        "total_tokens_saved": total_saved,
        "cost_saved_yuan": cost_saved,
        "cost_reduction_pct": cost_reduction_pct,
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
        "prefersStandardRequest": config.prefer_standard_request,
        "maxTokens": config.max_tokens,
        "paperPricing": {
            "inputYuanPerMillion": config.input_price_yuan_per_million,
            "outputYuanPerMillion": config.output_price_yuan_per_million,
        },
    }


def call_model(
    question_text: str,
    prompt_text: str,
    config: ModelConfig,
    reference_answer: str,
    verifier_model: str,
    cancel_event: threading.Event | None = None,
) -> Dict[str, Any]:
    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    max_retries = get_live_max_retries()
    parsed = None
    last_error = ""
    for attempt in range(1, max_retries + 1):
        if cancel_event and cancel_event.is_set():
            raise RunCancelledError("Run cancelled after the client disconnected.")
        try:
            with opener.open(make_api_request(prompt_text, config, stream=False), timeout=timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:
            if cancel_event and cancel_event.is_set():
                raise RunCancelledError("Run cancelled after the client disconnected.") from exc
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
        verifier_model=verifier_model,
        cancel_event=cancel_event,
    )


def stream_model(
    question_text: str,
    prompt_text: str,
    config: ModelConfig,
    reference_answer: str,
    verifier_model: str,
    on_delta: Callable[[str, str], None],
    on_retry: Callable[[int, int, str], None],
    on_fallback: Callable[[str], None],
    cancel_event: threading.Event | None = None,
) -> Dict[str, Any]:
    if config.prefer_standard_request:
        return call_model(
            question_text,
            prompt_text,
            config,
            reference_answer,
            verifier_model,
            cancel_event=cancel_event,
        )

    opener = build_opener()
    timeout_seconds = get_timeout_seconds()
    max_retries = get_stream_max_retries()
    last_error = ""

    for attempt in range(1, max_retries + 1):
        if cancel_event and cancel_event.is_set():
            raise RunCancelledError("Run cancelled after the client disconnected.")
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        usage: Dict[str, Any] = {}
        finish_reason: str | None = None
        parse_state = {
            "inside_think_tag": False,
            "saw_reasoning_signal": False,
            "saw_answer_content": False,
        }

        try:
            with opener.open(make_api_request(prompt_text, config, stream=True), timeout=timeout_seconds) as response:
                for raw_line in response:
                    if cancel_event and cancel_event.is_set():
                        raise RunCancelledError("Run cancelled after the client disconnected.")
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
                    reasoning_piece, answer_piece = extract_stream_delta_parts(delta, parse_state)
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
                verifier_model=verifier_model,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            if isinstance(exc, RunCancelledError) or (cancel_event and cancel_event.is_set()):
                raise RunCancelledError("Run cancelled after the client disconnected.") from exc
            last_error = format_upstream_error(exc)
            if attempt >= max_retries or not is_retryable_upstream_error(exc, last_error):
                break
            on_retry(attempt + 1, max_retries, last_error)
            time.sleep(retry_sleep_seconds(attempt))

    on_fallback(last_error)
    if cancel_event and cancel_event.is_set():
        raise RunCancelledError("Run cancelled after the client disconnected.")
    try:
        return call_model(
            question_text,
            prompt_text,
            config,
            reference_answer,
            verifier_model,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        fallback_error = format_upstream_error(exc)
        raise RuntimeError(
            f"Streaming failed after {max_retries} attempts: {last_error}; "
            f"fallback non-stream request failed: {fallback_error}"
        ) from exc


def serialize_live_comparison(
    example: Dict[str, Any], config: ModelConfig, verifier_model: str
) -> Dict[str, Any]:
    question = example["question"]
    reference_answer = example["answer"]
    skill_text = example["archived"][config.model_id]["trs"]["skill_text"]
    direct_prompt = build_direct_prompt(question)
    trs_prompt = build_prompt(config.prompt_template, question, skill_text)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_direct = pool.submit(call_model, question, direct_prompt, config, reference_answer, verifier_model)
        future_trs = pool.submit(call_model, question, trs_prompt, config, reference_answer, verifier_model)
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

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

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
        if content_length > MAX_REQUEST_BYTES:
            raise RequestTooLarge(MAX_REQUEST_BYTES)
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        return json.loads(body or "{}")

    def _client_ip(self) -> str:
        header_order = (
            "CF-Connecting-IP",
            "True-Client-IP",
            "Fly-Client-IP",
        )
        for header in header_order:
            candidate = extract_trusted_client_ip((self.headers.get(header) or "").strip())
            if candidate:
                return candidate
        forwarded = extract_trusted_client_ip((self.headers.get("X-Forwarded-For") or "").strip(), prefer_last=True)
        if forwarded:
            return forwarded
        return extract_trusted_client_ip(self.client_address[0]) or self.client_address[0]

    def _run_quota_payload(self) -> Dict[str, Any]:
        return self.server.run_quota_store.snapshot(self._client_ip())

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/examples":
            payload = {
                **self.server.examples_payload,
                "runQuota": self._run_quota_payload(),
            }
            self._send_json(payload)
            return

        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def _build_retrieved_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        example_id = str(payload.get("id") or "").strip()
        source_mode = (payload.get("sourceMode") or "").strip() or "custom"
        example = self.server.examples_by_id.get(example_id) if source_mode == "example" else None
        if example:
            question = example["question"]
            reference_answer = example["answer"]
            title = example.get("title") or ""
            subtitle = example.get("subtitle") or ""
            topic = example.get("topic") or "Example"
            difficulty = example.get("difficulty") or ""
            question_id = example.get("questionId") or ""
            benchmark_stats = deepcopy(example.get("benchmarkDirectStats")) or None
        else:
            question = normalize_required_text(payload.get("question"), "Question", MAX_CUSTOM_QUESTION_CHARS)
            reference_answer = normalize_required_text(
                payload.get("referenceAnswer") or payload.get("answer"),
                "Reference answer",
                MAX_REFERENCE_ANSWER_CHARS,
            )
            title = normalize_optional_text(payload.get("title"), MAX_OPTIONAL_FIELD_CHARS)
            subtitle = normalize_optional_text(payload.get("subtitle"), MAX_OPTIONAL_FIELD_CHARS)
            topic = normalize_optional_text(payload.get("topic"), MAX_OPTIONAL_FIELD_CHARS) or "Custom Input"
            difficulty = normalize_optional_text(payload.get("difficulty"), MAX_OPTIONAL_FIELD_CHARS) or "User"
            question_id = normalize_optional_text(payload.get("questionId"), MAX_OPTIONAL_FIELD_CHARS)
            benchmark_stats = deepcopy((self.server.examples_by_id.get(example_id, {}) or {}).get("benchmarkDirectStats")) or None
        dataset_ids = resolve_skill_dataset_ids(payload.get("skillDatasetIds"), self.server.skill_corpora)
        retrieval = retrieve_skill_entry(question, reference_answer, self.server.skill_corpora, dataset_ids)
        return build_preview_example(
            {
                "id": example_id or "custom-problem",
                "questionId": question_id,
                "title": title,
                "subtitle": subtitle,
                "topic": topic,
                "difficulty": difficulty,
                "benchmarkDirectStats": benchmark_stats,
                "question": question,
                "answer": reference_answer,
                "sourceMode": "example" if example else source_mode,
            },
            retrieval,
        )

    def _resolve_request(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], ModelConfig]:
        model_id = payload.get("modelId", "")

        if model_id not in MODEL_CONFIGS:
            raise ValueError(f"Unsupported modelId: {model_id}")

        if payload.get("question") or payload.get("referenceAnswer") or payload.get("answer"):
            preview = self._build_retrieved_preview(payload)
            return preview, MODEL_CONFIGS[model_id]

        example_id = payload.get("exampleId", "")
        example = self.server.examples_by_id.get(example_id)
        if not example:
            raise ValueError(f"Unknown exampleId: {example_id}")

        return example, MODEL_CONFIGS[model_id]

    def _handle_stream_run(
        self,
        example: Dict[str, Any],
        config: ModelConfig,
        verifier_model: str,
        run_id: int | None,
        run_quota: Dict[str, Any],
    ) -> None:
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
                "runQuota": run_quota,
            },
        )

        events: queue.Queue[tuple[str, Dict[str, Any]]] = queue.Queue()
        results: Dict[str, Dict[str, Any]] = {}
        failures: list[str] = []
        cancel_event = threading.Event()

        def emit(event_name: str, payload: Dict[str, Any]) -> None:
            if cancel_event.is_set():
                return
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
                    verifier_model=verifier_model,
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
                    cancel_event=cancel_event,
                )
                if lane == "trs":
                    result["skill_text"] = skill_text
                    result["skill_score"] = archived["trs"]["skill_score"]
                emit("lane_result", {"lane": lane, "result": result})
            except RunCancelledError:
                emit("lane_cancelled", {"lane": lane})
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
                elif event_name == "lane_cancelled":
                    completed_lanes += 1
                elif event_name == "lane_error":
                    failures.append(payload["error"])
                    completed_lanes += 1
                self._send_sse_event(event_name, payload)
            except BrokenPipeError:
                cancel_event.set()
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
            cancel_event.set()
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        run_slot_acquired = False
        retrieval_slot_acquired = False

        try:
            payload = self._read_json_body()

            if parsed.path == "/api/retrieve_skill":
                if not self.server.retrieve_capacity.acquire(blocking=False):
                    raise RetrievalCapacityExceeded(self.server.max_concurrent_retrievals)
                retrieval_slot_acquired = True
                preview = self._build_retrieved_preview(payload)
                serialized = serialize_preview(preview)
                self._send_json({"ok": True, "preview": serialized, "custom": serialized})
                return

            example, config = self._resolve_request(payload)
            verifier_model = resolve_verifier_model(payload.get("verifierModelId"))
            run_id = payload.get("runId")
            run_quota = None

            if parsed.path in {"/api/run", "/api/run_stream"}:
                if not self.server.run_capacity.acquire(blocking=False):
                    raise RunCapacityExceeded(self.server.max_concurrent_runs)
                run_slot_acquired = True
                run_quota = self.server.run_quota_store.consume(self._client_ip())

            if parsed.path == "/api/run":
                live = serialize_live_comparison(example, config, verifier_model)
                self._send_json(
                    {
                        "ok": True,
                        "exampleId": example["id"],
                        "mode": "custom" if example["id"] == "custom-problem" else "example",
                        "live": live,
                        "runQuota": run_quota,
                    }
                )
                return

            if parsed.path == "/api/run_stream":
                self._handle_stream_run(example, config, verifier_model, run_id, run_quota or self._run_quota_payload())
                return

            self._send_json({"error": f"Unknown endpoint: {parsed.path}"}, status=HTTPStatus.NOT_FOUND)
        except RequestTooLarge as exc:
            self._send_json(
                {"ok": False, "code": "request_too_large", "error": str(exc)},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except RunCapacityExceeded as exc:
            self._send_json(
                {"ok": False, "code": "run_capacity_exceeded", "error": str(exc)},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except RetrievalCapacityExceeded as exc:
            self._send_json(
                {"ok": False, "code": "retrieve_capacity_exceeded", "error": str(exc)},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except RunQuotaExceeded as exc:
            self._send_json(
                {
                    "ok": False,
                    "code": "run_quota_exceeded",
                    "error": str(exc),
                    "runQuota": exc.status,
                },
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if run_slot_acquired:
                self.server.run_capacity.release()
            if retrieval_slot_acquired:
                self.server.retrieve_capacity.release()


class DemoServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[DemoHandler]) -> None:
        super().__init__(server_address, handler_class)
        payload = load_examples_payload()
        self.examples_payload = payload
        self.examples_by_id = {example["id"]: example for example in payload["examples"]}
        self.examples_payload["precomputedExamplePreviews"] = load_precomputed_example_previews(
            self.examples_by_id
        )
        self.skill_corpora = build_skill_corpora(payload)
        self.run_quota_store = build_run_quota_store()
        self.max_concurrent_runs = MAX_CONCURRENT_RUNS
        self.run_capacity = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
        self.max_concurrent_retrievals = MAX_CONCURRENT_RETRIEVALS
        self.retrieve_capacity = threading.BoundedSemaphore(MAX_CONCURRENT_RETRIEVALS)
        self.examples_payload["skillDatasets"] = {
            "defaultSelectedIds": list(
                resolve_skill_dataset_ids(DEFAULT_SELECTED_SKILL_DATASET_IDS, self.skill_corpora)
            ),
            "options": [
                {
                    "id": option["id"],
                    "label": option["label"],
                    "docCount": self.skill_corpora[option["id"]]["doc_count"],
                    "sourceLabel": self.skill_corpora[option["id"]]["label"],
                }
                for option in SKILL_DATASET_OPTIONS
                if option["id"] in self.skill_corpora
            ],
        }
        self.examples_payload["runQuotaConfig"] = {
            "limit": RUN_QUOTA_MAX_RUNS,
            "windowSeconds": RUN_QUOTA_WINDOW_SECONDS,
            "backend": "redis" if RUN_QUOTA_REDIS_URL else "file",
        }
        self.examples_payload["runCapacityConfig"] = {
            "maxConcurrentRuns": MAX_CONCURRENT_RUNS,
            "maxConcurrentRetrievals": MAX_CONCURRENT_RETRIEVALS,
        }


def main() -> None:
    host = os.environ.get("TRS_DEMO_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("TRS_DEMO_PORT", "8080")))
    httpd = DemoServer((host, port), DemoHandler)
    quota_backend = httpd.examples_payload.get("runQuotaConfig", {}).get("backend", "file")
    print(f"TRS demo listening on http://{host}:{port} (run quota backend: {quota_backend})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
