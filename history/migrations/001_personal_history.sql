ALTER TABLE c2_history.jobs
    ADD COLUMN owner_user_id uuid REFERENCES c2_history.users(user_id),
    ADD COLUMN owner_bound_at timestamptz,
    ADD COLUMN owner_binding_reason text,
    ADD CONSTRAINT job_owner_binding CHECK (
        (owner_user_id IS NULL AND owner_bound_at IS NULL AND owner_binding_reason IS NULL)
        OR (owner_user_id IS NOT NULL AND owner_bound_at IS NOT NULL
            AND owner_binding_reason IS NOT NULL AND btrim(owner_binding_reason) <> ''));
CREATE INDEX jobs_owner ON c2_history.jobs(owner_user_id);
ALTER TABLE c2_history.sources ADD COLUMN contract text NOT NULL DEFAULT 'day4'
    CHECK (contract IN ('day4', 'final-mvp-20261008'));
CREATE TABLE c2_history.save_receipts (
    save_key text PRIMARY KEY CHECK (save_key <> '' AND save_key = btrim(save_key)),
    job_id uuid NOT NULL REFERENCES c2_history.jobs(job_id),
    owner_user_id uuid NOT NULL REFERENCES c2_history.users(user_id),
    manifest_sha256 text NOT NULL,
    event_count bigint NOT NULL CHECK (event_count > 0),
    saved_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX receipts_job ON c2_history.save_receipts(job_id);
