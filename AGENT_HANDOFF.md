# TRS Demo Agent Handoff

This file is the non-secret handoff for any future coding agent taking over the demo in this repo.

## Repo + deploy shape

- Repo root for the live demo: `/home/jovyan/zhaoguangxiang-data/shiqilong/prompt_bank/prompt-bank`
- Main backend entry: `app.py`
- Frontend files: `static/index.html`, `static/app.js`, `static/styles.css`
- Demo data lives in `data/`
- Deployment target in practice: `Render`
- Working branch policy from the user: always keep `main` up to date and push after each completed task

## What this demo is

- It is the live web demo for the TRS paper.
- The page compares `Direct` prompting against `TRS` prompting on curated math problems.
- The frontend streams two lanes in parallel:
  - `Direct`
  - `TRS`
- The page also shows:
  - retrieved skill card
  - chain of thought if the provider exposes it
  - final response
  - token usage
  - price / reduction summary
  - verifier verdict

## Core files

- `app.py`
  - all model configuration lives in `MODEL_CONFIGS`
  - verifier configuration lives in `VERIFIER_MODEL_OPTIONS`
  - API request construction lives in `build_api_payload`, `build_json_api_request`, `make_api_request`
  - streaming parse logic lives in `stream_model`, `extract_stream_delta_parts`, `extract_message_text_parts`
  - preview / retrieval logic lives in `_build_retrieved_preview`, `retrieve_skill_entry`, `build_skill_corpora`
  - HTTP routes:
    - `GET /api/examples`
    - `POST /api/retrieve_skill`
    - `POST /api/run`
    - `POST /api/run_stream`
    - `GET /api/health`

- `static/app.js`
  - page bootstrapping via `boot()`
  - model picker rendering via `renderModelSelector()`
  - skill dataset dropdown via `renderSkillDatasetControls()`
  - live streaming via `runComparison()` and `openRunStreamResponse()`
  - custom problem flow via `prepareCustomProblem()`

- `static/index.html`
  - top bar
  - left sidebar problem chooser
  - ClustrMaps widget block
  - live comparison panels

- `static/styles.css`
  - all layout + card styling
  - ClustrMaps white-background overrides live here

## Model integration rules

When adding a new model, usually touch `app.py` only.

Add a `ModelConfig` entry with:

- `model_id`
- `company`
- `provider`
- `family`
- `label`
- `api_model`
- `prompt_template`
- `input_price_yuan_per_million`
- `output_price_yuan_per_million`
- `supports_reasoning_trace`
- optional:
  - `max_tokens`
  - `max_tokens_param`
  - `temperature_override`
  - `extra_body`
  - `prefer_standard_request`

Important details:

- If a model only works at temperature `1`, set `temperature_override=1.0`.
- If a model exposes CoT via `reasoning_content`, current parser already supports it.
- If a model needs explicit thinking enablement, use `extra_body={"thinking": {"type": "enabled"}}` or model-specific settings.
- If streaming is unstable but non-stream is fine, set `prefer_standard_request=True` to bypass SSE upstream handling.

## Current model-specific gotchas

- `Kimi K2.6`
  - model id: `kimi26`
  - api model: `moonshot/moonshotai/kimi-k2.6`
  - must use `temperature=1`
  - exposes CoT in `reasoning_content`

- `DeepSeek V3.2`
  - model id: `deepseek32`
  - currently configured with `extra_body={"thinking": {"type": "enabled"}}`

- `DeepSeek V4 Flash`
  - model id: `deepseek4flash`
  - api model: `deepseek/deepseek-v4-flash`
  - streaming test succeeded with `reasoning_content`
  - configured with thinking enabled

- `DeepSeek V4 Pro`
  - model id: `deepseek4pro`
  - api model: `deepseek/deepseek-v4-pro`
  - streaming test succeeded with `reasoning_content`
  - configured with thinking enabled

- `Claude`
  - some Claude models need `extra_body` to reason properly
  - several are configured with adaptive or enabled thinking already

- `Grok-4`
  - one path uses standard request fallback because streaming can be awkward

## Skill datasets

- The top-right dropdown now shows only `Skills`.
- Current datasets come from `payload["skillDatasets"]`.
- Current ids in use are:
  - `deepmath`
  - `aops`
- Retrieval path:
  - frontend sends selected dataset ids
  - backend resolves them with `resolve_skill_dataset_ids`
  - retrieval then happens over the selected corpora only

## Curated examples + benchmark data

- Curated examples come from `data/demo_examples.json`
- Benchmark group structure comes from `data/benchmark_example_groups.json`
- Precomputed preview mapping comes from `data/example_preview_map.json`
- Benchmark pass-rate hints come from `data/benchmark_direct_accuracy.json`

## Rate limits / persistence

- Per-IP run quota is implemented server-side.
- Current defaults are controlled by env vars like:
  - `TRS_DEMO_RUN_QUOTA_MAX_RUNS`
  - `TRS_DEMO_RUN_QUOTA_WINDOW_SECONDS`
- Quota backend:
  - Redis if `TRS_DEMO_REDIS_URL` or `REDIS_URL` is set
  - local JSON fallback otherwise

## Render deployment notes

- Service entrypoint is `python app.py`
- Health route is `/api/health`
- API key must stay server-side only
- Redis persistence is optional but recommended for quota durability

## ClustrMaps notes

- The site currently uses the official ClustrMaps globe widget script in `static/index.html`.
- Browser inconsistency came from local container background styling, not from JavaScript support.
- White background overrides for Chrome / Safari variations are in `static/styles.css`.

## Git / workflow rules from the user

- User expects direct implementation, not just analysis.
- After finishing a task, push to GitHub `main`.
- The deployed site checks `main`, so `main` must be current.
- Never expose secrets in tracked files.

## Sensitive companion file

- There is a local-only companion file named `AGENT_HANDOFF.local.md`.
- It is git-ignored on purpose.
- That file contains secrets and machine-local operational notes that must not be pushed.
