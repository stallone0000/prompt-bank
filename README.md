# TRS DeepMath Live Demo

This repository contains a public-facing demo for the paper's TRS method on curated `DeepMath-103K` examples.

## Why not GitHub Pages alone?

`GitHub Pages` is convenient for static sites, but it is the wrong place to put this demo by itself because the page needs to call the `360` chat API and must not expose the API key in browser JavaScript.

This demo therefore uses:

- a static frontend
- a small Python backend
- server-side environment variables for the API key
- a per-IP run quota, backed by `Redis` / Render Key Value when available

If you want a public URL, deploy the whole repository as a single Python service or Docker container on a platform such as `Render`, `Railway`, or `Fly.io`.

## What the demo does

- uses only curated `DeepMath` examples from the paper / rebuttal workflow
- lets the reader pick one problem and one model family
- runs two live calls:
  - `Direct`: same prompt family, no skill prefix
  - `TRS`: same prompt family, plus the archived full-library skill card
- shows:
  - retrieved skill card
  - live reasoning trace
  - live answer
  - total token usage and paper-priced cost
  - estimated CoT reduction

## Local run

The curated demo payloads are checked into the repository under `data/`, so no local rebuild step is required for normal use.

1. Export the API key on the server side:

```bash
export TRS_DEMO_API_KEY="your-360-api-key"
```

2. Optional, if your environment needs the same internal proxy used by the experiments:

```bash
export TRS_DEMO_PROXY_URL="http://proxy.so.qihoo.net:8003"
```

3. Optional, to store per-IP quotas in Redis instead of the local JSON fallback:

```bash
export TRS_DEMO_REDIS_URL="redis://red-xxxxxxxx:6379"
```

4. Start the demo:

```bash
python app.py
```

5. Open:

```text
http://localhost:8080
```

## Environment variables

- `TRS_DEMO_API_KEY`
  - required unless `REBUTTAL_API_KEY` is already exported in the runtime
- `TRS_DEMO_API_URL`
  - default: `http://api.360.cn/v1/chat/completions`
- `TRS_DEMO_PROXY_URL`
  - optional HTTP/HTTPS proxy
- `TRS_DEMO_REDIS_URL`
  - optional Redis / Render Key Value URL for persistent per-IP quotas
- `TRS_DEMO_RUN_QUOTA_MAX_RUNS`
  - default: `10`
- `TRS_DEMO_TIMEOUT_SECONDS`
  - default: `300`
- `TRS_DEMO_MAX_TOKENS`
  - default: `32000`
- `TRS_DEMO_TEMPERATURE`
  - default: `0.7`
- `PORT`
  - default: `8080`

## Public deployment

### Docker-based deployment

The included `Dockerfile` is enough for platforms like `Render` or `Railway`.

Build command:

```bash
docker build -t trs-demo .
```

Run command:

```bash
docker run -p 8080:8080 -e TRS_DEMO_API_KEY="your-360-api-key" trs-demo
```

### Render / Railway

- deploy the repo root with the included `Dockerfile`
- `render.yaml` is already included for Render Blueprint deploys
- the included blueprint targets the `main` branch and defaults to Render's `free` plan
- set `TRS_DEMO_API_KEY` in the platform dashboard
- set `TRS_DEMO_REDIS_URL` if you want quotas to persist across redeploys
- set `TRS_DEMO_PROXY_URL` only if the deployment environment actually needs it
- if the platform needs a health check path, use `/api/health`
- switch the plan to `starter` later if you want to avoid free-tier sleep / cold starts

## Fastest public deployment

`Render` is the shortest path to a globally accessible URL.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/stallone0000/prompt-bank)

1. Push this repo to GitHub.
2. Make the repo public or grant Render access to it.
3. In Render, choose `New +` -> `Blueprint`.
4. Select this repo. Render will detect `render.yaml`.
5. Set `TRS_DEMO_API_KEY` in the service environment.
6. Optionally provision a Render Key Value instance and set `TRS_DEMO_REDIS_URL` to its internal URL.
7. Add `TRS_DEMO_PROXY_URL` only if the deployed environment cannot reach `http://api.360.cn` directly.
8. Click deploy. Render will return a public `https://...onrender.com` URL.

## Data files

The deployable demo now reads its curated payloads directly from checked-in files in `data/`, including:

- `data/demo_examples.json`
- `data/trs_skill_corpus.jsonl`
