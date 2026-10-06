CREATE SCHEMA IF NOT EXISTS c2_history;
CREATE TABLE IF NOT EXISTS c2_history.jobs (
    job_id uuid PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS c2_history.sources (
    source_key text PRIMARY KEY,
    last_line bigint NOT NULL DEFAULT 0 CHECK (last_line >= 0)
);
CREATE TABLE IF NOT EXISTS c2_history.events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_key text NOT NULL REFERENCES c2_history.sources(source_key),
    line_number bigint NOT NULL CHECK (line_number > 0),
    line_sha256 text NOT NULL,
    raw_line text NOT NULL,
    occurred_at timestamptz NOT NULL,
    job_id uuid NOT NULL REFERENCES c2_history.jobs(job_id),
    plan_id text, step_id text, request_id text,
    event text NOT NULL, outcome text, reason text,
    design_version integer, base_current_revision integer, observation_seq bigint,
    document jsonb NOT NULL,
    UNIQUE (source_key, line_number)
);
CREATE INDEX IF NOT EXISTS events_job_time ON c2_history.events(job_id, occurred_at, source_key, line_number);
CREATE INDEX IF NOT EXISTS events_reason ON c2_history.events(event, reason);
CREATE INDEX IF NOT EXISTS events_plan_step ON c2_history.events(job_id, plan_id, step_id);
CREATE TABLE IF NOT EXISTS c2_history.artifacts (
    job_id uuid NOT NULL REFERENCES c2_history.jobs(job_id),
    kind text NOT NULL CHECK (kind IN ('DESIGN', 'PLAN', 'BASE_CURRENT')),
    artifact_key text NOT NULL,
    adoption_event_id bigint NOT NULL REFERENCES c2_history.events(id),
    design_version integer NOT NULL CHECK (design_version > 0),
    plan_id text, base_current_revision integer,
    document jsonb NOT NULL,
    PRIMARY KEY (job_id, kind, artifact_key)
);
CREATE TABLE IF NOT EXISTS c2_history.users (
    user_id uuid PRIMARY KEY,
    username text NOT NULL UNIQUE CHECK (username <> '' AND username = btrim(username)),
    display_name text NOT NULL CHECK (display_name <> '' AND display_name = btrim(display_name)),
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
