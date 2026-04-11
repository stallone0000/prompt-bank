#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


APP_ROOT = Path(__file__).resolve().parents[1]


def find_workspace_root() -> Path:
    for candidate in [APP_ROOT, *APP_ROOT.parents]:
        if (candidate / "DeepMath-103K").exists():
            return candidate
    raise FileNotFoundError("Could not find DeepMath-103K in the current directory tree.")


WORKSPACE_ROOT = find_workspace_root()
OUTPUT_PATH = APP_ROOT / "data" / "demo_examples.json"

FILES = {
    "doubao_direct": WORKSPACE_ROOT / "DeepMath-103K" / "acl_rebuttal_math_dual_20260326" / "data" / "doubao_eval_500_direct.jsonl",
    "doubao_trs": WORKSPACE_ROOT / "DeepMath-103K" / "acl_rebuttal_math_dual_20260326" / "baseline_results" / "doubao_ours_full_500.jsonl",
    "oss_direct": WORKSPACE_ROOT / "DeepMath-103K" / "acl_rebuttal_math_dual_20260326" / "data" / "oss_eval_500_direct.jsonl",
    "oss_trs": WORKSPACE_ROOT / "DeepMath-103K" / "acl_rebuttal_math_dual_20260326" / "baseline_results" / "oss_ours_full_500.jsonl",
    "gemini_direct": WORKSPACE_ROOT / "DeepMath-103K" / "cot-bank" / "other-model" / "deepmath_1w_gemini3flash-qiniu.jsonl",
    "gemini_trs": WORKSPACE_ROOT / "DeepMath-103K" / "cot-bank" / "other-model" / "deepmath_1w_gemini3flash-qiniu_oss_guided_tryto.jsonl",
}

SELECTED = [
    {
        "id": "bisector-angle",
        "question_id": "q_93953",
        "title": "A Nested-Bisector Geometry Trap",
        "subtitle": "Parallel lines and angle chasing",
        "highlight": "Direct CoT wanders for a long time; TRS retrieves the exact bisector-geometry shortcut.",
    },
    {
        "id": "random-walk-bound",
        "question_id": "q_75171",
        "title": "Random Walk Maximum",
        "subtitle": "Asymptotic probability bound",
        "highlight": "The retrieved skill steers the model toward the right large-deviation viewpoint instead of ad hoc casework.",
    },
    {
        "id": "arctan-cubic-limit",
        "question_id": "q_34165",
        "title": "A Cubic-Order Arctan Limit",
        "subtitle": "High-order asymptotic cancellation",
        "highlight": "TRS points the model straight at the right expansion order, avoiding a long symbolic detour.",
    },
    {
        "id": "laplace-limit",
        "question_id": "q_71500",
        "title": "A Laplace-Style Limit",
        "subtitle": "Asymptotic integral on [0, pi]",
        "highlight": "The retrieved skill points directly at boundary minima and Laplace's method.",
    },
    {
        "id": "laurent-terms",
        "question_id": "q_66084",
        "title": "Counting Distinct Terms",
        "subtitle": "Laurent polynomial expansion",
        "highlight": "A short skill card collapses a long expansion search into an exponent-range argument.",
    },
]

MODEL_META = {
    "doubao": {
        "label": "Doubao Seed 1.8",
        "apiModel": "volcengine/doubao-seed-1-8",
        "promptStyle": "short",
        "supportsReasoningTrace": True,
        "paperPricing": {
            "inputYuanPerMillion": 0.8,
            "outputYuanPerMillion": 2.0,
        },
    },
    "oss": {
        "label": "GPT-OSS-120B",
        "apiModel": "qiniu/gpt-oss-120b",
        "promptStyle": "cod",
        "supportsReasoningTrace": False,
        "paperPricing": {
            "inputYuanPerMillion": 1.08,
            "outputYuanPerMillion": 5.4,
        },
    },
    "gemini": {
        "label": "Gemini 3 Flash",
        "apiModel": "cloudsway/gemini-3-flash-preview",
        "promptStyle": "tryto",
        "supportsReasoningTrace": False,
        "paperPricing": {
            "inputYuanPerMillion": 2.52,
            "outputYuanPerMillion": 15.12,
        },
    },
}


def load_jsonl(path: Path) -> Dict[str, Dict]:
    records: Dict[str, Dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            records[item["question_id"]] = item
    return records


def build_model_archive(direct_item: Dict, trs_item: Dict) -> Dict:
    return {
        "direct": {
            "verification": direct_item.get("gpt_verify", "UNKNOWN"),
        },
        "trs": {
            "verification": trs_item.get("heuristic_gpt_verify", "UNKNOWN"),
            "skill_text": trs_item.get("heuristic_used", ""),
            "skill_score": round(float(trs_item.get("heuristic_score", 0.0)), 3),
        },
    }


def main() -> None:
    loaded = {name: load_jsonl(path) for name, path in FILES.items()}
    examples = []

    for selected in SELECTED:
        qid = selected["question_id"]
        direct_doubao = loaded["doubao_direct"][qid]
        trs_doubao = loaded["doubao_trs"][qid]
        direct_oss = loaded["oss_direct"][qid]
        trs_oss = loaded["oss_trs"][qid]
        direct_gemini = loaded["gemini_direct"][qid]
        trs_gemini = loaded["gemini_trs"][qid]

        examples.append(
            {
                "id": selected["id"],
                "questionId": qid,
                "title": selected["title"],
                "subtitle": selected["subtitle"],
                "highlight": selected["highlight"],
                "question": direct_doubao["question"],
                "answer": direct_doubao["answer"],
                "topic": direct_doubao.get("topic", ""),
                "difficulty": direct_doubao.get("difficulty"),
                "archived": {
                    "doubao": build_model_archive(direct_doubao, trs_doubao),
                    "oss": build_model_archive(direct_oss, trs_oss),
                    "gemini": build_model_archive(direct_gemini, trs_gemini),
                },
            }
        )

    payload = {
        "title": "TRS DeepMath Live Demo",
        "dataset": "DeepMath-103K",
        "scope": "Curated DeepMath examples from the ACL rebuttal / final paper workflow. Live inference compares the direct prompt against the archived full-library TRS skill card for the same example and model family.",
        "note": "Archived data is used only to curate examples and retrieve the archived TRS skill card. Live runs use the current API response for token accounting and the original verifier prompt for correctness.",
        "models": MODEL_META,
        "examples": examples,
        "sources": {key: str(path) for key, path in FILES.items()},
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote demo data -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
