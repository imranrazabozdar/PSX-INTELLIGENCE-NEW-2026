CREATE TABLE source_items (
    source_item_id       INTEGER PRIMARY KEY,
    source_id            TEXT NOT NULL REFERENCES sources(source_id),
    canonical_url        TEXT,
    external_id          TEXT,
    title                TEXT,
    language             TEXT,
    published_at_utc     TEXT,
    published_at_raw     TEXT,
    published_tz_offset  TEXT,
    event_date           TEXT,
    collected_at_utc     TEXT NOT NULL,
    content_sha256       TEXT NOT NULL CHECK (length(content_sha256) = 64),
    permitted_excerpt    TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000),
    content_location     TEXT,
    access_status        TEXT NOT NULL DEFAULT 'public'
                           CHECK (access_status IN ('public','permitted','restricted','unavailable')),
    duplicate_of_item_id INTEGER REFERENCES source_items(source_item_id),
    relevance_score      REAL CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1),
    relevance_reason     TEXT, original_url TEXT, retrieval_method TEXT
    CHECK (retrieval_method IS NULL OR retrieval_method IN ('rss','atom','api','html','pdf','manual','seed')), collection_run_id INTEGER REFERENCES collector_runs(run_id), http_status INTEGER, document_type TEXT, publication_time_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (publication_time_status IN ('known','date_only','unavailable','unknown')), source_metadata_json TEXT
    CHECK (source_metadata_json IS NULL OR json_valid(source_metadata_json)),
    CHECK (canonical_url IS NOT NULL OR external_id IS NOT NULL),
    UNIQUE (source_id, canonical_url),
    UNIQUE (source_id, external_id)
);

CREATE TRIGGER trg_source_items_immutable BEFORE UPDATE OF
    source_id, canonical_url, external_id, collected_at_utc, content_sha256, published_at_raw
ON source_items
BEGIN SELECT RAISE(ABORT, 'source_items provenance fields are immutable; append a version instead'); END;

CREATE TRIGGER trg_source_items_no_delete BEFORE DELETE ON source_items
BEGIN SELECT RAISE(ABORT, 'source_items are append-only: deletion is not allowed'); END;

CREATE TRIGGER trg_source_items_original_url_immutable BEFORE UPDATE OF original_url, retrieval_method,
    collection_run_id, publication_time_status ON source_items
WHEN OLD.original_url IS NOT NULL OR OLD.collection_run_id IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'source_items provenance fields are immutable; append a version instead'); END;

CREATE INDEX ix_source_items_collected ON source_items(collected_at_utc);

CREATE INDEX ix_source_items_event_date ON source_items(event_date);

CREATE INDEX ix_source_items_hash ON source_items(content_sha256);

CREATE INDEX ix_source_items_published ON source_items(published_at_utc);

CREATE INDEX ix_source_items_run ON source_items(collection_run_id);
