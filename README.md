# TRS DeepMath Live Demo

This repository contains a public-facing demo for the paper's TRS method on curated `DeepMath-103K` examples.

It now supports:

- `Google` sign-in via `Supabase Auth`
- authenticated `Run` access
- per-user click and run event logging into `Supabase Postgres`

## Why not GitHub Pages alone?

`GitHub Pages` is convenient for static sites, but it is the wrong place to put this demo by itself because the page needs to call the `360` chat API and must not expose the API key in browser JavaScript.

This demo therefore uses:

- a static frontend
- a small Python backend
- server-side environment variables for the API key

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
export SUPABASE_URL="https://your-project-id.supabase.co"
export SUPABASE_ANON_KEY="your-supabase-anon-key"
export SUPABASE_DB_URL="postgresql://postgres:password@db.your-project-id.supabase.co:5432/postgres?sslmode=require"
```

2. Optional, if your environment needs the same internal proxy used by the experiments:

```bash
export TRS_DEMO_PROXY_URL="http://proxy.so.qihoo.net:8003"
```

3. Start the demo:

```bash
python app.py
```

4. Open:

```text
http://localhost:8080
```

## Environment variables

- `TRS_DEMO_API_KEY`
  - required unless `REBUTTAL_API_KEY` is already exported in the runtime
- `SUPABASE_URL`
  - required to enable Google sign-in
- `SUPABASE_ANON_KEY`
  - required to enable Google sign-in
- `SUPABASE_DB_URL`
  - required to persist user click / run events into `public.user_events`
- `TRS_DEMO_API_URL`
  - default: `http://api.360.cn/v1/chat/completions`
- `TRS_DEMO_PROXY_URL`
  - optional HTTP/HTTPS proxy
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
docker run -p 8080:8080 \
  -e TRS_DEMO_API_KEY="your-360-api-key" \
  -e SUPABASE_URL="https://your-project-id.supabase.co" \
  -e SUPABASE_ANON_KEY="your-supabase-anon-key" \
  -e SUPABASE_DB_URL="postgresql://postgres:password@db.your-project-id.supabase.co:5432/postgres?sslmode=require" \
  trs-demo
```

### Render / Railway

- deploy the repo root with the included `Dockerfile`
- `render.yaml` is already included for Render Blueprint deploys
- the included blueprint targets the `main` branch and defaults to Render's `free` plan
- set `TRS_DEMO_API_KEY` in the platform dashboard
- set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_DB_URL` in the platform dashboard
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
6. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_DB_URL` in the service environment.
7. Add `TRS_DEMO_PROXY_URL` only if the deployed environment cannot reach `http://api.360.cn` directly.
8. Click deploy. Render will return a public `https://...onrender.com` URL.

## Supabase setup

1. Create a Supabase project.
2. In `Authentication -> Providers -> Google`, enable `Google`.
3. Add your local URL and Render URL to the Google redirect allowlist in Supabase.
4. In the Supabase SQL editor, run `supabase/user_events.sql`.

If `SUPABASE_DB_URL` is configured, the app also tries to create `public.user_events` automatically at startup.

The event log is stored in `public.user_events`. You can inspect it directly in:

- `Supabase Dashboard -> Table Editor -> user_events`
- `Supabase Dashboard -> SQL Editor`

## Data files

The deployable demo now reads its curated payloads directly from checked-in files in `data/`, including:

- `data/demo_examples.json`
- `data/trs_skill_corpus.jsonl`
