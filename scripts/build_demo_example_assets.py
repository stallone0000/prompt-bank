#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib import error, request


APP_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = APP_DIR.parent
BENCHMARK_DIR = WORKSPACE_DIR / "benchmark-test" / "benchmarks"
BENCHMARK_GROUPS_PATH = APP_DIR / "data" / "benchmark_example_groups.json"
BENCHMARK_TYPE_PATH = APP_DIR / "data" / "benchmark_problem_types.json"
PREVIEW_MAP_PATH = APP_DIR / "data" / "example_preview_map.json"

API_URL = os.environ.get("QIHOO_API_URL", "http://api.360.cn/v1/chat/completions")
API_PROXY = os.environ.get("QIHOO_PROXY_URL", "http://proxy.so.qihoo.net:8003")
DEFAULT_MODEL = "qiniu/gpt-oss-20b"

BENCHMARK_GROUP_SPECS = [
    {
        "id": "benchmark-group::hmmt_nov_2025",
        "label": "HMMT November 2025",
        "subtitle": "30 benchmark problems",
        "kind": "benchmark",
        "parts": [("hmmt_nov_2025", "P")],
    },
    {
        "id": "benchmark-group::aime_2024",
        "label": "AIME 2024",
        "subtitle": "30 benchmark problems",
        "kind": "benchmark",
        "parts": [("aime_2024_i", "I"), ("aime_2024_ii", "II")],
    },
    {
        "id": "benchmark-group::aime_2025",
        "label": "AIME 2025",
        "subtitle": "30 benchmark problems",
        "kind": "benchmark",
        "parts": [("aime_2025", "P")],
    },
    {
        "id": "benchmark-group::aime_2026",
        "label": "AIME 2026",
        "subtitle": "30 benchmark problems",
        "kind": "benchmark",
        "parts": [("aime_2026", "P")],
    },
]

LATEX_FIXUPS = {
    r"\overlien{": r"\overline{",
}

ASY_BLOCK_RE = re.compile(r"<asy>.*?</asy>", re.DOTALL)
TIKZ_BLOCK_RE = re.compile(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", re.DOTALL)
ITEMIZE_RE = re.compile(r"\\begin\{itemize\}(.*?)\\end\{itemize\}", re.DOTALL)
ITEM_RE = re.compile(r"\\item\s*(.*?)(?=(?:\\item|$))", re.DOTALL)
LABEL_PREFIX_RE = re.compile(r"^(problem type|label|topic)\s*:\s*", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_BLANK_RE = re.compile(r"\n{3,}")
ALLOWED_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 -]{0,47}$")
BAD_LABEL_TOKENS = {
    "let",
    "maybe",
    "compute",
    "approximate",
    "find",
    "suppose",
    "where",
    "because",
    "problem",
    "slanted",
}


def repo_module():
    sys.path.insert(0, str(APP_DIR))
    import app  # type: ignore

    return app


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sanitize_question_text(text: str) -> str:
    sanitized = text.strip()
    for source, target in LATEX_FIXUPS.items():
        sanitized = sanitized.replace(source, target)

    sanitized = ASY_BLOCK_RE.sub("\n\n(Sample diagrams omitted in the demo view.)", sanitized)
    sanitized = TIKZ_BLOCK_RE.sub("\n\n(Diagram omitted in the demo view.)", sanitized)

    def replace_itemize(match: re.Match[str]) -> str:
        items = []
        for item_match in ITEM_RE.finditer(match.group(1)):
            item = " ".join(item_match.group(1).split())
            if item:
                items.append(f"- {item}")
        return "\n" + "\n".join(items) + "\n" if items else "\n"

    sanitized = ITEMIZE_RE.sub(replace_itemize, sanitized)
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in sanitized.splitlines()]
    sanitized = "\n".join(line for line in lines if line or (line == "" and lines))
    sanitized = MULTI_BLANK_RE.sub("\n\n", sanitized).strip()
    return sanitized


def opener_with_proxy() -> request.OpenerDirector:
    return request.build_opener(
        request.ProxyHandler(
            {
                "http": API_PROXY,
                "https": API_PROXY,
            }
        )
    )


def extract_label_from_reasoning(reasoning_text: str) -> str:
    candidates: list[str] = []
    candidates.extend(re.findall(r'"([^"\n]{2,48})"', reasoning_text))
    candidates.extend(re.findall(r"'([^'\n]{2,48})'", reasoning_text))
    for candidate in reversed(candidates):
        cleaned = normalize_label(candidate)
        if cleaned:
            return cleaned
    tail = reasoning_text.strip().splitlines()[-1:] or [""]
    return normalize_label(tail[0])


def normalize_label(raw_label: str) -> str:
    cleaned = (raw_label or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.splitlines()[0].strip()
    cleaned = LABEL_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.strip("`'\".:- ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return ""
    return cleaned.title()


def is_plausible_label(label: str) -> bool:
    cleaned = normalize_label(label)
    if not cleaned:
        return False
    if not ALLOWED_LABEL_RE.match(cleaned):
        return False
    words = cleaned.split()
    if not (1 <= len(words) <= 4):
        return False
    if any(word.lower() in BAD_LABEL_TOKENS for word in words):
        return False
    return True


def classify_problem_type(
    opener: request.OpenerDirector,
    api_key: str,
    problem_text: str,
    *,
    model: str,
    retries: int = 4,
) -> str:
    prompt = (
        "You are labeling a math olympiad benchmark problem for a compact dropdown UI.\n"
        "Return exactly one short English problem-type label in Title Case.\n"
        "Requirements:\n"
        "- 1 to 4 words\n"
        "- No punctuation except a hyphen if truly needed\n"
        "- Prefer standard olympiad topic labels such as Circle Geometry, Triangle Geometry, "
        "Combinatorics, Probability, Base Number Theory, Functional Equation, Coordinate Geometry, "
        "Combinatorial Game, Logarithms, Recurrence, or Inequality\n"
        "- Ignore any omitted-diagram note\n\n"
        f"Problem:\n{problem_text}\n\n"
        "Label:"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Host": "api.360.cn",
    }

    last_error = "Unknown classification failure."
    for attempt in range(1, retries + 1):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 512,
            "temperature": 0.1,
            "content_filter": False,
        }
        req = request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with opener.open(req, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
            message = ((body.get("choices") or [{}])[0].get("message") or {})
            label = normalize_label(str(message.get("content") or ""))
            if not label:
                label = extract_label_from_reasoning(str(message.get("reasoning_content") or ""))
            if is_plausible_label(label):
                return label
            last_error = f"The model returned an implausible label: {label!r}"
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {detail[:400]}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(min(8.0, 0.8 * attempt))
    raise RuntimeError(last_error)


def build_question_title(display_name: str, problem_idx: int) -> str:
    return f"{display_name} · Problem {problem_idx}"


def build_option_code(prefix: str, problem_idx: int) -> str:
    return f"{prefix}-{problem_idx:02d}" if prefix != "P" else f"P{problem_idx:02d}"


def build_benchmark_groups(type_labels: dict[str, str]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    benchmark_cache: dict[str, tuple[str, list[dict[str, Any]]]] = {}

    for benchmark_name in {part[0] for spec in BENCHMARK_GROUP_SPECS for part in spec["parts"]}:
        meta_path = BENCHMARK_DIR / benchmark_name / "meta.json"
        question_path = BENCHMARK_DIR / benchmark_name / "questions.jsonl"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        benchmark_cache[benchmark_name] = (meta["display_name"], load_jsonl(question_path))

    for spec in BENCHMARK_GROUP_SPECS:
        options: list[dict[str, Any]] = []
        for benchmark_name, prefix in spec["parts"]:
            display_name, rows = benchmark_cache[benchmark_name]
            for row in rows:
                label = type_labels[row["question_id"]]
                problem_idx = int(row["problem_idx"])
                options.append(
                    {
                        "id": f"benchmark::{benchmark_name}::{problem_idx}",
                        "questionId": row["question_id"],
                        "title": build_question_title(display_name, problem_idx),
                        "optionLabel": f"{build_option_code(prefix, problem_idx)} · {label}",
                        "subtitle": spec["label"],
                        "question": sanitize_question_text(row["question"]),
                        "answer": str(row["answer"]).strip(),
                        "topic": label,
                        "difficulty": "Benchmark",
                        "benchmark": benchmark_name,
                    }
                )

        groups.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "subtitle": spec["subtitle"],
                "kind": spec["kind"],
                "options": options,
            }
        )

    return {"groups": groups}


def all_dataset_combinations(dataset_ids: list[str]) -> list[list[str]]:
    combos: list[list[str]] = []
    for size in range(1, len(dataset_ids) + 1):
        for combo in itertools.combinations(dataset_ids, size):
            combos.append(list(combo))
    return combos


def build_preview_map() -> dict[str, Any]:
    demo_app = repo_module()
    payload = demo_app.load_examples_payload()
    corpora = demo_app.build_skill_corpora(payload)
    dataset_ids = [option["id"] for option in demo_app.SKILL_DATASET_OPTIONS if option["id"] in corpora]
    combos = all_dataset_combinations(dataset_ids)
    previews: dict[str, Any] = {}

    total = len(payload["examples"]) * len(combos)
    completed = 0
    for example in payload["examples"]:
        base_context = {
            "id": example["id"],
            "questionId": example.get("questionId") or "",
            "title": example.get("title") or "",
            "subtitle": example.get("subtitle") or "",
            "topic": example.get("topic") or "",
            "difficulty": example.get("difficulty") or "",
            "question": example["question"],
            "answer": example["answer"],
            "sourceMode": "example",
        }
        for combo in combos:
            retrieval = demo_app.retrieve_skill_entry(
                example["question"],
                example["answer"],
                corpora,
                combo,
            )
            preview = demo_app.serialize_preview(demo_app.build_preview_example(base_context, retrieval))
            previews[f"{example['id']}@@{','.join(sorted(combo))}"] = preview
            completed += 1
            if completed % 60 == 0 or completed == total:
                print(f"[preview-map] built {completed}/{total}", flush=True)

    return {
        "generatedAt": int(time.time()),
        "datasetIds": dataset_ids,
        "previews": previews,
    }


def build_benchmark_type_labels(api_key: str, *, model: str, workers: int) -> dict[str, Any]:
    opener = opener_with_proxy()
    existing = load_json(BENCHMARK_TYPE_PATH, {"labels": {}})
    cached_labels: dict[str, str] = {
        question_id: normalize_label(label)
        for question_id, label in (existing.get("labels") or {}).items()
        if is_plausible_label(label)
    }

    benchmark_rows: list[dict[str, Any]] = []
    for spec in BENCHMARK_GROUP_SPECS:
        for benchmark_name, _prefix in spec["parts"]:
            meta_path = BENCHMARK_DIR / benchmark_name / "meta.json"
            question_path = BENCHMARK_DIR / benchmark_name / "questions.jsonl"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for row in load_jsonl(question_path):
                benchmark_rows.append(
                    {
                        "question_id": row["question_id"],
                        "benchmark": benchmark_name,
                        "title": build_question_title(meta["display_name"], int(row["problem_idx"])),
                        "question": sanitize_question_text(row["question"]),
                    }
                )

    pending = [row for row in benchmark_rows if row["question_id"] not in cached_labels]
    if pending:
        print(f"[types] classifying {len(pending)} benchmark problems with {model}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {
            pool.submit(
                classify_problem_type,
                opener,
                api_key,
                row["question"],
                model=model,
            ): row
            for row in pending
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            row = future_map[future]
            label = future.result()
            cached_labels[row["question_id"]] = label
            if index % 10 == 0 or index == len(future_map):
                print(f"[types] finished {index}/{len(future_map)}", flush=True)

    ordered_labels = {
        row["question_id"]: cached_labels[row["question_id"]]
        for row in benchmark_rows
    }
    return {
        "generatedAt": int(time.time()),
        "model": model,
        "labels": ordered_labels,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--skip-types", action="store_true")
    parser.add_argument("--skip-previews", action="store_true")
    parser.add_argument("--api-key", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = (
        args.api_key
        or os.environ.get("TRS_DEMO_API_KEY")
        or os.environ.get("REBUTTAL_API_KEY")
        or os.environ.get("QIHOO_API_KEY")
        or ""
    ).strip()

    type_payload = load_json(BENCHMARK_TYPE_PATH, {"labels": {}})
    if not args.skip_types:
        if not api_key:
            raise RuntimeError("Missing API key. Set --api-key or TRS_DEMO_API_KEY / REBUTTAL_API_KEY / QIHOO_API_KEY.")
        type_payload = build_benchmark_type_labels(api_key, model=args.model, workers=args.workers)
        write_json(BENCHMARK_TYPE_PATH, type_payload)
        print(f"[types] wrote {BENCHMARK_TYPE_PATH}", flush=True)

    groups_payload = build_benchmark_groups(type_payload["labels"])
    write_json(BENCHMARK_GROUPS_PATH, groups_payload)
    print(f"[groups] wrote {BENCHMARK_GROUPS_PATH}", flush=True)

    if not args.skip_previews:
        preview_payload = build_preview_map()
        write_json(PREVIEW_MAP_PATH, preview_payload)
        print(f"[preview-map] wrote {PREVIEW_MAP_PATH}", flush=True)


if __name__ == "__main__":
    main()
