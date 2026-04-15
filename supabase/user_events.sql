CREATE TABLE IF NOT EXISTS public.user_events (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    request_path TEXT NOT NULL DEFAULT '',
    source_mode TEXT,
    example_id TEXT,
    question_id TEXT,
    model_id TEXT,
    verifier_model_id TEXT,
    skill_dataset_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    event_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_events_user_id_created_at_idx
    ON public.user_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS user_events_event_type_created_at_idx
    ON public.user_events (event_type, created_at DESC);
