-- PROPOSED (not applied to production): records human review decisions on model candidates.
-- event_extractions is append-only by trigger, so decisions cannot be stored on the candidate row itself.
-- Statements are separated by the marker line below so the runner can send them one by one (trigger bodies contain ';').
CREATE TABLE extraction_reviews (
    review_id       INTEGER PRIMARY KEY,
    extraction_id   INTEGER NOT NULL REFERENCES event_extractions(extraction_id),
    decision        TEXT NOT NULL CHECK (decision IN ('accept','reject','needs_more_evidence')),
    reviewer        TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes           TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    event_id        INTEGER REFERENCES events(event_id),
    decided_at_utc  TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK ((decision = 'accept') = (event_id IS NOT NULL))
);
-- statement-break

CREATE INDEX ix_extraction_reviews_extraction ON extraction_reviews(extraction_id, review_id);
-- statement-break

CREATE TRIGGER trg_extraction_reviews_no_update BEFORE UPDATE ON extraction_reviews
BEGIN SELECT RAISE(ABORT, 'extraction_reviews are append-only: record a new decision instead'); END;
-- statement-break

CREATE TRIGGER trg_extraction_reviews_no_delete BEFORE DELETE ON extraction_reviews
BEGIN SELECT RAISE(ABORT, 'extraction_reviews are append-only'); END;
-- statement-break

CREATE VIEW v_review_queue AS
SELECT e.extraction_id, e.source_item_id, e.created_at_utc, e.model, e.schema_version, e.confidence, e.extracted_json
FROM event_extractions e
WHERE e.needs_human_review = 1
  AND COALESCE((SELECT r.decision FROM extraction_reviews r WHERE r.extraction_id = e.extraction_id
                ORDER BY r.review_id DESC LIMIT 1), 'needs_more_evidence') = 'needs_more_evidence';
