CREATE TABLE c2_history.design_publications (
    job_id uuid NOT NULL REFERENCES c2_history.jobs(job_id),
    design_version integer NOT NULL CHECK (design_version > 0),
    design jsonb NOT NULL,
    is_published boolean NOT NULL DEFAULT false,
    published_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, design_version)
);
