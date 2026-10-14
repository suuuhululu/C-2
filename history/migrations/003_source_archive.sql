ALTER TABLE c2_history.sources
    ADD COLUMN ingest_policy text NOT NULL DEFAULT 'all'
        CHECK (ingest_policy IN ('all', 'operational-v1')),
    ADD COLUMN prefix_sha256 text,
    ADD COLUMN archive_path text,
    ADD COLUMN archive_sha256 text,
    ADD COLUMN archive_bytes bigint CHECK (archive_bytes >= 0);
