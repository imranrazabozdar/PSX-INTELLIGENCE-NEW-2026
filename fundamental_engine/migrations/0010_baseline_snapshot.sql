-- BASELINE SNAPSHOT of the production Turso schema (migrations 1-10), regenerated from the live database on 2026-11-09.
-- The original per-migration SQL files and their checksums are not in version control, so this single file
-- replaces versions 1-10 for fresh databases. It is NOT a replay of the original migrations.
-- Live schema_migrations: 1 reference_and_sources, 2 events_and_evidence, 3 metrics_research_and_outcomes,
-- 4 media_operations_watchlist, 5 dataset_loads, 6 collection_engine, 7 intelligence_engine, 8 exposure_mapping,
-- 9 impact_assessments, 10 market_ohlcv.

CREATE TABLE alerts_predictions (
    alert_id       INTEGER PRIMARY KEY,
    company_id     TEXT REFERENCES companies(company_id),
    event_id       INTEGER REFERENCES events(event_id),
    created_at_utc TEXT NOT NULL,
    reference_price REAL,
    reference_price_at_utc TEXT,
    direction      TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    horizon_sessions INTEGER CHECK (horizon_sessions IS NULL OR horizon_sessions > 0),
    confidence     REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    thesis         TEXT NOT NULL,
    invalidation   TEXT,
    snapshot_json  TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    CHECK (company_id IS NOT NULL OR event_id IS NOT NULL)
);

CREATE TABLE analyses (
    analysis_id    INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES events(event_id),
    company_id     TEXT NOT NULL REFERENCES companies(company_id),
    analysis_version INTEGER NOT NULL CHECK (analysis_version >= 1),
    label          TEXT NOT NULL CHECK (label IN ('quantitative','qualitative')),
    transmission   TEXT,
    financial_impact_json TEXT CHECK (financial_impact_json IS NULL OR json_valid(financial_impact_json)),
    missing_inputs_json   TEXT CHECK (missing_inputs_json IS NULL OR json_valid(missing_inputs_json)),
    confidence     REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    risk           TEXT,
    model_version  TEXT,
    prompt_version TEXT,
    calculation_version TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE (event_id, company_id, analysis_version)
);

CREATE TABLE collector_checkpoints (
    source_id              TEXT PRIMARY KEY REFERENCES sources(source_id),
    endpoint_url           TEXT NOT NULL,
    etag                   TEXT,
    last_modified          TEXT,
    last_seen_external_id  TEXT,
    last_seen_published_utc TEXT,
    cursor                 TEXT,
    updated_at_utc         TEXT NOT NULL
);

CREATE TABLE collector_runs (
    run_id          INTEGER PRIMARY KEY,
    job             TEXT NOT NULL,
    source_id       TEXT REFERENCES sources(source_id),
    started_at_utc  TEXT NOT NULL,
    finished_at_utc TEXT,
    status          TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','partial','dry_run')),
    items_fetched   INTEGER NOT NULL DEFAULT 0,
    items_accepted  INTEGER NOT NULL DEFAULT 0,
    items_rejected  INTEGER NOT NULL DEFAULT 0,
    errors          TEXT,
    quota_usage_json TEXT CHECK (quota_usage_json IS NULL OR json_valid(quota_usage_json)),
    log_reference   TEXT
, items_duplicate INTEGER NOT NULL DEFAULT 0, items_new_version INTEGER NOT NULL DEFAULT 0, items_failed INTEGER NOT NULL DEFAULT 0, http_requests INTEGER NOT NULL DEFAULT 0, http_status INTEGER, duration_ms INTEGER, not_modified INTEGER NOT NULL DEFAULT 0 CHECK (not_modified IN (0,1)));

CREATE TABLE commodity_prices (
    price_id       INTEGER PRIMARY KEY,
    commodity      TEXT NOT NULL,
    grade_contract TEXT NOT NULL,
    location       TEXT,
    observation_date TEXT NOT NULL,
    published_at_utc TEXT,
    price          REAL NOT NULL,
    currency       TEXT NOT NULL,
    unit           TEXT NOT NULL,
    price_type     TEXT NOT NULL CHECK (price_type IN ('spot','futures','administered','assessed','contract')),
    methodology    TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (commodity, grade_contract, location, observation_date, price_type, source_item_id)
);

CREATE TABLE companies (
    company_id            TEXT PRIMARY KEY CHECK (company_id GLOB 'cmp-*'),
    legal_name            TEXT NOT NULL,
    listing_status        TEXT NOT NULL CHECK (listing_status IN ('listed','delisted','suspended','unknown')),
    fiscal_year_end_month INTEGER CHECK (fiscal_year_end_month BETWEEN 1 AND 12),
    share_class           TEXT NOT NULL DEFAULT 'ordinary',
    website               TEXT,
    business_summary      TEXT CHECK (business_summary IS NULL OR length(business_summary) <= 600),
    profile_source_item_id INTEGER REFERENCES source_items(source_item_id),
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL
);

CREATE TABLE company_aliases (
    alias_id         INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    alias            TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    alias_type       TEXT NOT NULL CHECK (alias_type IN ('ticker','legal_name','short_name','former_name',
                                                         'abbreviation','brand','misspelling')),
    language         TEXT NOT NULL DEFAULT 'en',
    confidence       TEXT NOT NULL CHECK (confidence IN ('verified','derived','candidate')),
    valid_from       TEXT,
    valid_to         TEXT,
    source_item_id   INTEGER REFERENCES source_items(source_item_id),
    evidence         TEXT,
    UNIQUE (company_id, alias_normalized, alias_type)
);

CREATE TABLE company_classifications (
    classification_id INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    sector_id         TEXT NOT NULL REFERENCES sectors(sector_id),
    valid_from        TEXT,
    valid_to          TEXT,
    verified_at_utc   TEXT NOT NULL,
    source_item_id    INTEGER REFERENCES source_items(source_item_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (company_id, sector_id, valid_from)
);

CREATE TABLE company_exposures (
    exposure_id       INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    segment_id        INTEGER REFERENCES company_segments(segment_id),
    exposure_kind     TEXT NOT NULL CHECK (exposure_kind IN ('input','product','market','geography','customer',
                                                             'supplier','fx','debt','regulation','logistics','energy')),
    subject           TEXT NOT NULL,
    scope             TEXT,
    confidence        TEXT NOT NULL CHECK (confidence IN ('documented','probable','uncertain')),
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    evidence_excerpt  TEXT NOT NULL,
    valid_from        TEXT,
    valid_to          TEXT,
    last_verified_utc TEXT NOT NULL
);

CREATE TABLE company_identifiers (
    identifier_id   INTEGER PRIMARY KEY,
    company_id      TEXT NOT NULL REFERENCES companies(company_id),
    id_type         TEXT NOT NULL CHECK (id_type IN ('psx_ticker','isin')),
    value           TEXT NOT NULL,
    valid_from      TEXT,            -- NULL = start date not known (never guessed)
    valid_to        TEXT,            -- NULL = still current
    verified_at_utc TEXT NOT NULL,   -- when this project last verified the record
    source_item_id  INTEGER REFERENCES source_items(source_item_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (id_type <> 'psx_ticker' OR value GLOB '[A-Z0-9]*'),
    UNIQUE (id_type, value, valid_from)
);

CREATE TABLE company_relationships (
    relationship_id    INTEGER PRIMARY KEY,
    supersedes_relationship_id INTEGER UNIQUE REFERENCES company_relationships(relationship_id),
    parent_company_id  TEXT NOT NULL REFERENCES companies(company_id),
    child_company_id   TEXT REFERENCES companies(company_id),   -- NULL when the child is not in the master
    child_name         TEXT NOT NULL CHECK (length(trim(child_name)) > 0),
    relationship_type  TEXT NOT NULL CHECK (relationship_type IN ('subsidiary','associate','joint_venture',
                                                                  'holding_company','common_control')),
    ownership_pct      REAL CHECK (ownership_pct IS NULL OR ownership_pct BETWEEN 0 AND 100),
    valid_from         TEXT,
    valid_to           TEXT,
    evidence_status    TEXT NOT NULL CHECK (evidence_status IN ('confirmed','strongly_supported','potential',
                                                                'unverified','rejected')),
    source_item_id     INTEGER REFERENCES source_items(source_item_id),
    evidence_excerpt   TEXT CHECK (evidence_excerpt IS NULL OR length(evidence_excerpt) BETWEEN 1 AND 1000),
    is_synthetic       INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    change_reason      TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    recorded_by        TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
    recorded_at_utc    TEXT NOT NULL,
    CHECK (child_company_id IS NULL OR child_company_id <> parent_company_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (evidence_status NOT IN ('confirmed','strongly_supported','potential')
           OR (source_item_id IS NOT NULL AND evidence_excerpt IS NOT NULL))
);

CREATE TABLE company_segments (
    segment_id        INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    segment_name      TEXT NOT NULL,
    segment_type      TEXT NOT NULL CHECK (segment_type IN ('business','product','geography')),
    revenue_share_pct REAL CHECK (revenue_share_pct IS NULL OR revenue_share_pct BETWEEN 0 AND 100),
    period            TEXT,
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    evidence_excerpt  TEXT NOT NULL,
    last_verified_utc TEXT NOT NULL
);

CREATE TABLE company_status_history (
    status_event_id    INTEGER PRIMARY KEY,
    company_id         TEXT NOT NULL REFERENCES companies(company_id),
    status             TEXT NOT NULL CHECK (status IN ('listed','delisted','suspended','merged_into',
                                                       'renamed','ticker_changed')),
    effective_date     TEXT,
    date_precision     TEXT NOT NULL CHECK (date_precision IN ('exact','observed','month','year','unknown')),
    related_company_id TEXT REFERENCES companies(company_id),
    details            TEXT,
    source_item_id     INTEGER REFERENCES source_items(source_item_id),
    recorded_at_utc    TEXT NOT NULL
);

CREATE TABLE dataset_loads (
    dataset        TEXT PRIMARY KEY,
    sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
    loaded_at_utc  TEXT NOT NULL,
    record_count   INTEGER NOT NULL CHECK (record_count >= 0)
);

CREATE TABLE event_companies (
    event_company_id  INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    exposure_type     TEXT NOT NULL CHECK (exposure_type IN ('direct','indirect','uncertain','excluded')),
    impact_direction  TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (impact_direction IN ('positive','negative','mixed','neutral','unknown')),
    channel           TEXT,
    rationale         TEXT NOT NULL,
    confidence        REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    reviewer_status   TEXT NOT NULL DEFAULT 'pending' CHECK (reviewer_status IN ('pending','accepted','rejected')),
    created_at_utc    TEXT NOT NULL,
    UNIQUE (event_id, company_id)
);

CREATE TABLE event_evidence (
    evidence_id       INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    claim             TEXT NOT NULL,
    claim_type        TEXT NOT NULL CHECK (claim_type IN (
                        'verified_fact','official_statement','news_report','analyst_interpretation',
                        'personal_opinion','prediction','rumour','advertisement','model_inference','unclear')),
    relation          TEXT NOT NULL CHECK (relation IN ('supports','contradicts','context')),
    excerpt           TEXT NOT NULL CHECK (length(excerpt) BETWEEN 1 AND 1000),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (verification_state IN ('unverified','checked_against_primary','corroborated',
                                                      'disputed','refuted')),
    is_independent    INTEGER CHECK (is_independent IS NULL OR is_independent IN (0,1)),
    recorded_at_utc   TEXT NOT NULL,
    recorded_by       TEXT NOT NULL,
    UNIQUE (event_id, source_item_id, claim)
);

CREATE TABLE event_extractions (
    extraction_id      INTEGER PRIMARY KEY,
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    event_id           INTEGER REFERENCES events(event_id),
    call_id            INTEGER REFERENCES llm_calls(call_id),
    schema_version     TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    model              TEXT NOT NULL,
    extracted_json     TEXT NOT NULL CHECK (json_valid(extracted_json)),
    confidence         REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    confidence_explanation TEXT NOT NULL,
    needs_human_review INTEGER NOT NULL CHECK (needs_human_review IN (0,1)),
    review_reasons_json TEXT NOT NULL CHECK (json_valid(review_reasons_json)),
    provenance_json    TEXT NOT NULL CHECK (json_valid(provenance_json)),
    created_at_utc     TEXT NOT NULL,
    UNIQUE (source_item_id, schema_version, prompt_version, model)
);

CREATE TABLE event_revisions (
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    revision_no       INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc   TEXT NOT NULL,
    status_stage      TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    headline          TEXT NOT NULL,
    summary           TEXT,
    snapshot_json     TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason     TEXT NOT NULL,
    changed_by        TEXT NOT NULL,
    model_version     TEXT,
    prompt_version    TEXT,
    PRIMARY KEY (event_id, revision_no)
);

CREATE TABLE events (
    event_id          INTEGER PRIMARY KEY,
    event_type        TEXT NOT NULL,
    headline          TEXT NOT NULL,
    summary           TEXT,
    event_date        TEXT,
    event_date_precision TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (event_date_precision IN ('exact','day','month','quarter','year','unknown')),
    geography         TEXT,
    status_stage      TEXT NOT NULL CHECK (status_stage IN (
                        'rumour','discussion','proposal','consultation','committee_recommendation',
                        'approval','notification','implementation','amendment','delay','suspension',
                        'reversal','confirmed_fact','not_applicable')),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (verification_state IN ('unverified','single_source','corroborated',
                                                      'primary_confirmed','disputed','refuted')),
    direction         TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude         TEXT NOT NULL DEFAULT 'unknown' CHECK (magnitude IN ('low','medium','high','unknown')),
    novelty           TEXT NOT NULL DEFAULT 'unknown' CHECK (novelty IN ('new','update','repeat','unknown')),
    horizon           TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (horizon IN ('immediate','days_weeks','quarterly','annual','long_term','unknown')),
    confidence        REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    first_seen_at_utc TEXT NOT NULL,
    current_revision  INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    created_at_utc    TEXT NOT NULL,
    updated_at_utc    TEXT NOT NULL
);

CREATE TABLE evidence_retractions (
    retraction_id      INTEGER PRIMARY KEY,
    record_table       TEXT NOT NULL CHECK (record_table IN ('event_evidence','company_exposures')),
    record_id          INTEGER NOT NULL,
    reason             TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    retracted_by       TEXT NOT NULL CHECK (length(trim(retracted_by)) >= 2),
    retracted_at_utc   TEXT NOT NULL,
    UNIQUE (record_table, record_id)
);

CREATE TABLE exposure_candidate_evidence (
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    role               TEXT NOT NULL CHECK (role IN ('claim','company_specific')),
    event_evidence_id  INTEGER REFERENCES event_evidence(evidence_id),
    company_exposure_id INTEGER REFERENCES company_exposures(exposure_id),
    relationship_id    INTEGER REFERENCES company_relationships(relationship_id),
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    added_at_utc       TEXT NOT NULL,
    CHECK ((event_evidence_id IS NOT NULL) + (company_exposure_id IS NOT NULL) + (relationship_id IS NOT NULL) = 1),
    CHECK (role = 'company_specific' OR event_evidence_id IS NOT NULL)
);

CREATE TABLE exposure_candidate_revisions (
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    revision_no        INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc    TEXT NOT NULL,
    evidence_status    TEXT NOT NULL,
    review_status      TEXT NOT NULL,
    last_review_id     INTEGER REFERENCES exposure_reviews(review_id),
    snapshot_json      TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason      TEXT NOT NULL,
    changed_by         TEXT NOT NULL,
    PRIMARY KEY (candidate_id, revision_no)
);

CREATE TABLE exposure_candidates (
    candidate_id       INTEGER PRIMARY KEY,
    event_id           INTEGER NOT NULL REFERENCES events(event_id),
    company_id         TEXT NOT NULL REFERENCES companies(company_id),
    psx_symbol         TEXT,
    exposure_category  TEXT NOT NULL CHECK (exposure_category IN ('operational','financial','regulatory',
                                                                  'macroeconomic','geopolitical','sector')),
    exposure_subtype   TEXT NOT NULL,
    exposure_level     TEXT NOT NULL CHECK (exposure_level IN ('direct','indirect')),
    impact_direction   TEXT NOT NULL CHECK (impact_direction IN ('positive','negative','mixed','neutral','unknown')),
    segment_id         INTEGER REFERENCES company_segments(segment_id),
    mechanism          TEXT NOT NULL CHECK (length(trim(mechanism)) > 0),
    explanation        TEXT NOT NULL,
    missing_evidence_json TEXT NOT NULL CHECK (json_valid(missing_evidence_json)),
    confidence         REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_status    TEXT NOT NULL CHECK (evidence_status IN ('confirmed','strongly_supported','potential',
                                                                'unverified','rejected')),
    review_status      TEXT NOT NULL CHECK (review_status IN ('pending','needs_review','accepted','rejected')),
    review_reasons_json TEXT NOT NULL CHECK (json_valid(review_reasons_json)),
    last_review_id     INTEGER REFERENCES exposure_reviews(review_id),
    origin             TEXT NOT NULL CHECK (origin IN ('rule','llm_suggestion')),
    rule_id            TEXT,
    ruleset_version    TEXT NOT NULL,
    model              TEXT,
    prompt_version     TEXT,
    schema_version     TEXT NOT NULL,
    is_synthetic       INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    current_revision   INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    change_reason      TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    changed_by         TEXT NOT NULL CHECK (length(trim(changed_by)) > 0),
    created_at_utc     TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL,
    CHECK ((evidence_status = 'confirmed') = (review_status = 'accepted')),
    CHECK (evidence_status <> 'rejected' OR review_status IN ('rejected','needs_review','pending')),
    CHECK (origin <> 'llm_suggestion' OR evidence_status NOT IN ('strongly_supported','confirmed')),
    UNIQUE (event_id, company_id, exposure_category, exposure_subtype, mechanism, ruleset_version)
);

CREATE TABLE exposure_reviews (
    review_id          INTEGER PRIMARY KEY,
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    decision           TEXT NOT NULL CHECK (decision IN ('accept','reject','needs_more_evidence','evidence_revoked')),
    reviewer           TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    decided_at_utc     TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    evidence_status_at_decision TEXT NOT NULL
);

CREATE TABLE financial_metrics (
    metric_id      INTEGER PRIMARY KEY,
    company_id     TEXT NOT NULL REFERENCES companies(company_id),
    period_end     TEXT NOT NULL,
    period_type    TEXT NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','H1','H2','9M','FY','TTM')),
    metric         TEXT NOT NULL,
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    currency       TEXT,
    basis          TEXT NOT NULL CHECK (basis IN ('reported','restated','calculated','estimated')),
    calculation_method TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL,
    UNIQUE (company_id, period_end, period_type, metric, basis, source_item_id)
);

CREATE TABLE fund_holdings (
    holding_id     INTEGER PRIMARY KEY,
    fund_id        TEXT NOT NULL REFERENCES funds(fund_id),
    company_id     TEXT REFERENCES companies(company_id),
    report_date    TEXT NOT NULL,
    shares         REAL,
    weight_pct     REAL CHECK (weight_pct IS NULL OR weight_pct BETWEEN 0 AND 100),
    reported_value REAL,
    currency       TEXT,
    sector_allocation_pct REAL,
    aum            REAL,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (fund_id, company_id, report_date, source_item_id)
);

CREATE TABLE funds (
    fund_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    amc            TEXT NOT NULL,
    category       TEXT,
    benchmark      TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE impact_assessment_inputs (
    input_id                   INTEGER PRIMARY KEY,
    assessment_id              INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    input_kind                 TEXT NOT NULL CHECK (input_kind IN ('exposure_candidate','event_evidence',
                                                                   'financial_metric','commodity_price')),
    exposure_candidate_id      INTEGER REFERENCES exposure_candidates(candidate_id),
    exposure_candidate_revision INTEGER,
    event_evidence_id          INTEGER REFERENCES event_evidence(evidence_id),
    financial_metric_id        INTEGER REFERENCES financial_metrics(metric_id),
    commodity_price_id         INTEGER REFERENCES commodity_prices(price_id),
    source_item_id             INTEGER NOT NULL REFERENCES source_items(source_item_id),
    step_no                    INTEGER CHECK (step_no IS NULL OR step_no >= 1),
    added_at_utc               TEXT NOT NULL,
    FOREIGN KEY (exposure_candidate_id, exposure_candidate_revision)
        REFERENCES exposure_candidate_revisions(candidate_id, revision_no),
    CHECK ((exposure_candidate_id IS NOT NULL) + (event_evidence_id IS NOT NULL)
           + (financial_metric_id IS NOT NULL) + (commodity_price_id IS NOT NULL) = 1),
    CHECK ((input_kind = 'exposure_candidate') = (exposure_candidate_id IS NOT NULL)),
    CHECK ((exposure_candidate_id IS NULL) = (exposure_candidate_revision IS NULL)),
    CHECK ((input_kind = 'event_evidence') = (event_evidence_id IS NOT NULL)),
    CHECK ((input_kind = 'financial_metric') = (financial_metric_id IS NOT NULL)),
    CHECK ((input_kind = 'commodity_price') = (commodity_price_id IS NOT NULL))
);

CREATE TABLE impact_assessment_revisions (
    assessment_id      INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no        INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc    TEXT NOT NULL,
    previous_status    TEXT,
    new_status         TEXT NOT NULL,
    status_reason      TEXT NOT NULL,
    actor_type         TEXT NOT NULL,
    actor              TEXT NOT NULL,
    review_id          INTEGER REFERENCES impact_reviews(review_id),
    snapshot_json      TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
    PRIMARY KEY (assessment_id, revision_no)
);

CREATE TABLE impact_assessments (
    assessment_id        INTEGER PRIMARY KEY,
    event_id             INTEGER NOT NULL REFERENCES events(event_id),
    event_revision_no    INTEGER NOT NULL,
    company_id           TEXT NOT NULL REFERENCES companies(company_id),
    mechanism_id         TEXT NOT NULL CHECK (mechanism_id GLOB 'T[1-9]' AND length(mechanism_id) = 2),
    transmission_version TEXT NOT NULL CHECK (length(trim(transmission_version)) > 0),
    ruleset_version      TEXT NOT NULL,
    calculation_version  TEXT,
    scenario_kind        TEXT NOT NULL CHECK (scenario_kind IN ('current','hypothetical','historical_test')),
    assessment_status    TEXT NOT NULL CHECK (assessment_status IN ('scenario_only','provisional','needs_review',
                             'needs_revalidation','confirmed_conclusion','withdrawn_evidence_invalid',
                             'rejected_by_review')),
    status_reason        TEXT NOT NULL,
    direction            TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude_level      TEXT NOT NULL CHECK (magnitude_level IN ('low','medium','high','not_assessable')),
    magnitude_basis      TEXT NOT NULL CHECK (magnitude_basis IN ('qualitative','deterministic_model',
                                                                  'financially_quantified')),
    horizon              TEXT NOT NULL CHECK (horizon IN ('short','medium','long','unknown')),
    evidence_confidence  TEXT NOT NULL CHECK (evidence_confidence IN ('low','medium','high')),
    exposure_confidence  TEXT NOT NULL CHECK (exposure_confidence IN ('low','medium','high')),
    direction_confidence TEXT NOT NULL CHECK (direction_confidence IN ('low','medium','high')),
    magnitude_confidence TEXT NOT NULL CHECK (magnitude_confidence IN ('low','medium','high')),
    scenario_uncertainty TEXT NOT NULL CHECK (scenario_uncertainty IN ('narrow','wide','undetermined')),
    confidence_reasons_json TEXT NOT NULL CHECK (json_valid(confidence_reasons_json)),
    affected_lines_json  TEXT NOT NULL CHECK (json_valid(affected_lines_json)),
    counter_evidence_json TEXT NOT NULL CHECK (json_valid(counter_evidence_json)),
    missing_inputs_json  TEXT NOT NULL CHECK (json_valid(missing_inputs_json)),
    quantification_json  TEXT CHECK (quantification_json IS NULL OR json_valid(quantification_json)),
    market_check         TEXT NOT NULL DEFAULT 'not_evaluable' CHECK (market_check = 'not_evaluable'),
    analysis_id          INTEGER REFERENCES analyses(analysis_id),
    expiry_policy_version TEXT REFERENCES impact_expiry_policy_versions(policy_version),
    freshness_basis      TEXT NOT NULL CHECK (freshness_basis IN ('explicit_source_expiry','policy_expiry',
                                                                  'not_established')),
    is_synthetic         INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    current_revision     INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    last_review_id       INTEGER REFERENCES impact_reviews(review_id),
    change_reason        TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    changed_by           TEXT NOT NULL CHECK (length(trim(changed_by)) >= 2),
    actor_type           TEXT NOT NULL CHECK (actor_type IN ('human','system')),
    created_at_utc       TEXT NOT NULL,
    updated_at_utc       TEXT NOT NULL,
    FOREIGN KEY (event_id, event_revision_no) REFERENCES event_revisions(event_id, revision_no),
    -- financially quantified results need a quantification record; others must not carry one
    CHECK ((magnitude_basis = 'financially_quantified') = (quantification_json IS NOT NULL)),
    CHECK ((freshness_basis = 'policy_expiry') = (expiry_policy_version IS NOT NULL)),
    -- status <-> reason <-> actor (system withdrawal and human rejection can never be confused)
    CHECK (
        (assessment_status = 'scenario_only' AND status_reason IN ('created_scenario','revalidated'))
     OR (assessment_status = 'provisional' AND status_reason IN ('created_eligible','revalidated','reinstated'))
     OR (assessment_status = 'needs_review' AND status_reason IN ('created_needs_review','event_disputed',
                                    'reviewer_needs_more_evidence','freshness_not_established'))
     OR (assessment_status = 'needs_revalidation' AND status_reason IN ('evidence_revoked','evidence_superseded',
                                    'evidence_expired','evidence_retracted','source_restricted','exposure_rejected',
                                    'reviewer_requested_revalidation'))
     OR (assessment_status = 'confirmed_conclusion' AND status_reason = 'reviewer_accepted')
     OR (assessment_status = 'withdrawn_evidence_invalid' AND status_reason IN ('event_refuted','evidence_revoked',
                                    'evidence_superseded','evidence_expired','evidence_retracted',
                                    'source_restricted','exposure_rejected'))
     OR (assessment_status = 'rejected_by_review' AND status_reason = 'reviewer_rejected')),
    CHECK (status_reason NOT IN ('reviewer_accepted','reviewer_rejected','reviewer_needs_more_evidence',
                                 'reviewer_requested_revalidation','reinstated') OR actor_type = 'human'),
    CHECK (assessment_status <> 'withdrawn_evidence_invalid' OR actor_type = 'system'),
    CHECK (assessment_status <> 'rejected_by_review' OR actor_type = 'human'),
    UNIQUE (event_id, company_id, mechanism_id, scenario_kind, transmission_version)
);

CREATE TABLE impact_expiry_policy_events (
    policy_event_id    INTEGER PRIMARY KEY,
    policy_version     TEXT NOT NULL REFERENCES impact_expiry_policy_versions(policy_version),
    event_type         TEXT NOT NULL CHECK (event_type IN ('approved','retired')),
    actor              TEXT NOT NULL CHECK (length(trim(actor)) >= 2),
    effective_from_utc TEXT,
    effective_to_utc   TEXT,
    recorded_at_utc    TEXT NOT NULL,
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    CHECK (event_type <> 'approved' OR (effective_from_utc IS NOT NULL AND effective_to_utc IS NULL)),
    CHECK (event_type <> 'retired' OR (effective_to_utc IS NOT NULL AND effective_from_utc IS NULL)),
    UNIQUE (policy_version, event_type)
);

CREATE TABLE impact_expiry_policy_versions (
    policy_version     TEXT PRIMARY KEY CHECK (length(trim(policy_version)) > 0),
    rules_json         TEXT NOT NULL CHECK (json_valid(rules_json)),
    rationale          TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    drafted_by         TEXT NOT NULL CHECK (length(trim(drafted_by)) >= 2),
    drafted_at_utc     TEXT NOT NULL,
    supersedes_version TEXT REFERENCES impact_expiry_policy_versions(policy_version)
);

CREATE TABLE impact_reviews (
    review_id          INTEGER PRIMARY KEY,
    assessment_id      INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    decision           TEXT NOT NULL CHECK (decision IN ('accept','reject','request_revalidation',
                                                         'needs_more_evidence')),
    reviewer           TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    decided_at_utc     TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    status_at_decision TEXT NOT NULL
);

CREATE TABLE impact_scenarios (
    assessment_id    INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no      INTEGER NOT NULL,
    scenario_case    TEXT NOT NULL CHECK (scenario_case IN ('base','optimistic','adverse')),
    direction        TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude_level  TEXT NOT NULL CHECK (magnitude_level IN ('low','medium','high','not_assessable')),
    assumptions_json TEXT NOT NULL CHECK (json_valid(assumptions_json)),
    PRIMARY KEY (assessment_id, revision_no, scenario_case),
    FOREIGN KEY (assessment_id, revision_no) REFERENCES impact_assessment_revisions(assessment_id, revision_no)
);

CREATE TABLE impact_transmission_steps (
    assessment_id  INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no    INTEGER NOT NULL,
    step_no        INTEGER NOT NULL CHECK (step_no >= 1),
    from_variable  TEXT NOT NULL CHECK (length(trim(from_variable)) > 0),
    to_variable    TEXT NOT NULL CHECK (length(trim(to_variable)) > 0),
    sign           INTEGER CHECK (sign IS NULL OR sign IN (-1, 0, 1)),
    lag_horizon    TEXT NOT NULL CHECK (lag_horizon IN ('short','medium','long','unknown')),
    explanation    TEXT NOT NULL CHECK (length(trim(explanation)) > 0),
    PRIMARY KEY (assessment_id, revision_no, step_no),
    FOREIGN KEY (assessment_id, revision_no) REFERENCES impact_assessment_revisions(assessment_id, revision_no)
);

CREATE TABLE index_memberships (
    membership_id   INTEGER PRIMARY KEY,
    index_code      TEXT NOT NULL,
    company_id      TEXT NOT NULL REFERENCES companies(company_id),
    observed_at_utc TEXT NOT NULL,
    source_item_id  INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (index_code, company_id, observed_at_utc)
);

CREATE TABLE llm_calls (
    call_id            INTEGER PRIMARY KEY,
    called_at_utc      TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    prompt_id          TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    prompt_sha256      TEXT NOT NULL CHECK (length(prompt_sha256) = 64),
    input_sha256       TEXT NOT NULL CHECK (length(input_sha256) = 64),
    input_tokens       INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cost_usd           REAL NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    outcome            TEXT NOT NULL CHECK (outcome IN ('ok','cached','invalid_output','error','refused_budget',
                                                        'refused_kill_switch','not_connected')),
    error              TEXT
);

CREATE TABLE market_bar_corrections (
    correction_id     INTEGER PRIMARY KEY,
    source_id         TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    bar_start_utc     TEXT NOT NULL,
    open              REAL NOT NULL,
    high              REAL NOT NULL,
    low               REAL NOT NULL,
    close             REAL NOT NULL,
    volume            REAL NOT NULL CHECK (volume >= 0),
    retrieved_at_utc  TEXT NOT NULL,
    collection_run_id INTEGER REFERENCES collector_runs(run_id),
    CHECK (low > 0 AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
    FOREIGN KEY (source_id, symbol, timeframe, bar_start_utc)
        REFERENCES market_bars(source_id, symbol, timeframe, bar_start_utc)
);

CREATE TABLE market_bars (
    source_id         TEXT NOT NULL REFERENCES sources(source_id),
    symbol            TEXT NOT NULL CHECK (symbol GLOB '[A-Z0-9]*' AND length(symbol) BETWEEN 1 AND 16
                                           AND symbol NOT GLOB '*[^A-Z0-9]*'),
    timeframe         TEXT NOT NULL CHECK (timeframe IN ('1m','1h','4h','1d')),
    bar_start_utc     TEXT NOT NULL CHECK (bar_start_utc GLOB
                          '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:00Z'),
    session_date_pkt  TEXT NOT NULL CHECK (session_date_pkt GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    open              REAL NOT NULL,
    high              REAL NOT NULL,
    low               REAL NOT NULL,
    close             REAL NOT NULL,
    volume            REAL NOT NULL CHECK (volume >= 0),
    retrieved_at_utc  TEXT NOT NULL,
    collection_run_id INTEGER REFERENCES collector_runs(run_id),
    CHECK (low > 0 AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
    CHECK (timeframe <> '1d' OR substr(bar_start_utc, 12) = '00:00:00Z'),
    CHECK (timeframe NOT IN ('1h','4h') OR substr(bar_start_utc, 15) = '00:00Z'),
    PRIMARY KEY (source_id, symbol, timeframe, bar_start_utc)
);

CREATE TABLE market_outcomes (
    outcome_id     INTEGER PRIMARY KEY,
    alert_id       INTEGER NOT NULL REFERENCES alerts_predictions(alert_id),
    evaluation_date TEXT NOT NULL,
    sessions_after INTEGER NOT NULL CHECK (sessions_after > 0),
    stock_return   REAL,
    benchmark_return REAL,
    sector_return  REAL,
    dividend_adjusted_return REAL,
    costs          REAL,
    outcome        TEXT CHECK (outcome IN ('hit','miss','partial','invalidated','not_evaluable')),
    computed_at_utc TEXT NOT NULL,
    UNIQUE (alert_id, sessions_after)
);

CREATE TABLE media_accounts (
    account_id      INTEGER PRIMARY KEY,
    platform        TEXT NOT NULL CHECK (platform IN ('x','youtube')),
    handle          TEXT,
    platform_account_id TEXT,
    supplied_url    TEXT,
    display_name    TEXT,
    person_or_org   TEXT,
    account_type    TEXT,
    monitoring_purpose TEXT,
    identity_verification TEXT NOT NULL DEFAULT 'unverified'
                      CHECK (identity_verification IN ('unverified','pending_confirmation','verified','rejected')),
    reliability_tier TEXT NOT NULL DEFAULT 'unrated',
    monitoring_status TEXT NOT NULL DEFAULT 'disabled'
                      CHECK (monitoring_status IN ('disabled','pending_handle','active','paused')),
    source_id       TEXT REFERENCES sources(source_id),
    notes           TEXT,
    created_at_utc  TEXT NOT NULL, category TEXT, access_status TEXT NOT NULL DEFAULT 'no_authorised_access'
    CHECK (access_status IN ('no_authorised_access','official_api_required','authorised','not_applicable')),
    CHECK (handle IS NOT NULL OR monitoring_status = 'pending_handle'),
    -- collection may only be active for a verified identity
    CHECK (monitoring_status <> 'active' OR identity_verification = 'verified')
);

CREATE TABLE media_event_links (
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    event_id        INTEGER NOT NULL REFERENCES events(event_id),
    evidence_role   TEXT NOT NULL CHECK (evidence_role IN ('lead','supporting','contradicting','context')),
    independence    TEXT NOT NULL CHECK (independence IN ('independent','same_source','repost','syndicated','unknown')),
    confidence      REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    PRIMARY KEY (media_item_id, event_id)
);

CREATE TABLE media_items (
    media_item_id   INTEGER PRIMARY KEY,
    platform        TEXT NOT NULL CHECK (platform IN ('x','youtube')),
    external_id     TEXT NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES media_accounts(account_id),
    canonical_url   TEXT NOT NULL,
    published_at_utc TEXT,
    published_at_raw TEXT,
    collected_at_utc TEXT NOT NULL,
    language        TEXT,
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64),
    text_pointer    TEXT,
    permitted_excerpt TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000),
    transcript_status TEXT NOT NULL DEFAULT 'not_applicable'
                      CHECK (transcript_status IN ('not_applicable','available','unavailable','pending','manual')),
    relevance_priority TEXT CHECK (relevance_priority IN ('high','conditional','low')),
    relevance_reason TEXT,
    rejection_reason TEXT,
    UNIQUE (platform, external_id)
);

CREATE TABLE media_mentions (
    mention_id      INTEGER PRIMARY KEY,
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    company_id      TEXT REFERENCES companies(company_id),
    entity          TEXT NOT NULL,
    mention_type    TEXT NOT NULL,
    sentiment       TEXT CHECK (sentiment IN ('positive','negative','mixed','neutral')),
    claim_type      TEXT NOT NULL CHECK (claim_type IN (
                      'verified_fact','official_statement','news_report','analyst_interpretation',
                      'personal_opinion','prediction','rumour','advertisement','unclear')),
    context_excerpt TEXT,
    relevance_score REAL CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1)
);

CREATE TABLE media_metrics_history (
    media_item_id   INTEGER REFERENCES media_items(media_item_id),
    account_id      INTEGER REFERENCES media_accounts(account_id),
    observed_at_utc TEXT NOT NULL,
    views INTEGER, likes INTEGER, reposts INTEGER, replies INTEGER, quotes INTEGER,
    CHECK (media_item_id IS NOT NULL OR account_id IS NOT NULL)
);

CREATE TABLE media_predictions (
    prediction_id   INTEGER PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES media_accounts(account_id),
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    company_id      TEXT REFERENCES companies(company_id),
    direction       TEXT CHECK (direction IN ('positive','negative','mixed','neutral')),
    target          REAL,
    horizon         TEXT,
    prediction_date TEXT NOT NULL,
    assumptions     TEXT,
    result          TEXT,
    evaluated_at_utc TEXT
);

CREATE TABLE research_views (
    view_id        INTEGER PRIMARY KEY,
    author_source_id TEXT NOT NULL REFERENCES sources(source_id),
    company_id     TEXT REFERENCES companies(company_id),
    view_date      TEXT NOT NULL,
    direction      TEXT CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    recommendation TEXT,
    target_price   REAL,
    currency       TEXT,
    horizon        TEXT,
    valuation_method TEXT,
    assumptions    TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL
);

CREATE TABLE schema_migrations (
    version        INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    checksum       TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at_utc TEXT NOT NULL,
    result         TEXT NOT NULL CHECK (result IN ('applied'))
);

CREATE TABLE sector_metrics (
    metric_id      INTEGER PRIMARY KEY,
    sector_id      TEXT REFERENCES sectors(sector_id),
    company_id     TEXT REFERENCES companies(company_id),
    metric         TEXT NOT NULL,
    period         TEXT NOT NULL,
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    geography      TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL,
    CHECK (sector_id IS NOT NULL OR company_id IS NOT NULL)
);

CREATE TABLE sectors (
    sector_id      TEXT PRIMARY KEY,
    scheme         TEXT NOT NULL CHECK (scheme IN ('PSX')),
    name           TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (scheme, name)
);

CREATE TABLE source_item_versions (
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    version_no        INTEGER NOT NULL CHECK (version_no >= 1),
    content_sha256    TEXT NOT NULL CHECK (length(content_sha256) = 64),
    collected_at_utc  TEXT NOT NULL,
    permitted_excerpt TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000), collection_run_id INTEGER REFERENCES collector_runs(run_id), title TEXT,
    PRIMARY KEY (source_item_id, version_no),
    UNIQUE (source_item_id, content_sha256)
);

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

CREATE TABLE sources (
    source_id          TEXT PRIMARY KEY CHECK (source_id GLOB '[a-z0-9]*' AND length(source_id) <= 64),
    name               TEXT NOT NULL,
    source_type        TEXT NOT NULL CHECK (source_type IN (
                         'exchange','official_regulator','government','news_media','international_news',
                         'broker_research','asset_manager','industry_body','data_provider',
                         'social_x','social_youtube','other')),
    domain             TEXT,
    platform           TEXT,
    owner              TEXT,
    reliability_tier   TEXT NOT NULL DEFAULT 'unrated'
                         CHECK (reliability_tier IN ('primary_official','established_media','specialist',
                                                     'commentary','unrated')),
    access_method      TEXT NOT NULL DEFAULT 'pending_review'
                         CHECK (access_method IN ('rss','official_api','html_permitted','pdf','manual',
                                                  'authorised_provider','pending_review','not_permitted')),
    access_status      TEXT NOT NULL DEFAULT 'unverified'
                         CHECK (access_status IN ('unverified','verified_permitted','restricted',
                                                  'licence_required','blocked')),
    terms_notes        TEXT,
    terms_reviewed_at_utc TEXT,
    update_cadence     TEXT,
    enabled            INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    last_success_at_utc TEXT,
    notes              TEXT,
    created_at_utc     TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL, official_url TEXT, category TEXT, subcategory TEXT, geographic_coverage TEXT, industries_json TEXT CHECK (industries_json IS NULL OR json_valid(industries_json)), related_companies_json TEXT
    CHECK (related_companies_json IS NULL OR json_valid(related_companies_json)), content_format TEXT NOT NULL DEFAULT 'unknown'
    CHECK (content_format IN ('rss','atom','api','html','pdf','mixed','social','video','unknown')), feed_url TEXT, adapter TEXT, retention_mode TEXT NOT NULL DEFAULT 'metadata_only'
    CHECK (retention_mode IN ('metadata_only','excerpt','full_text_permitted')), terms_status TEXT NOT NULL DEFAULT 'not_reviewed'
    CHECK (terms_status IN ('not_reviewed','not_found','reviewed_ok','restricted','prohibits_automation',
                            'licence_required','approved')), licensing_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (licensing_status IN ('unknown','public_domain','open_licence','free_with_attribution',
                                'personal_non_commercial','permission_required','licence_required','paid_api')), verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('unverified','url_verified','identity_verified','unreachable')), lifecycle_status TEXT NOT NULL DEFAULT 'NOT REVIEWED'
    CHECK (lifecycle_status IN ('NOT REVIEWED','REVIEWED','APPROVED','RESTRICTED','LICENCE REQUIRED',
                                'BLOCKED','IMPLEMENTED','TESTED','ACTIVE','DISABLED')), priority INTEGER CHECK (priority IS NULL OR priority BETWEEN 1 AND 5), collection_frequency_minutes INTEGER
    CHECK (collection_frequency_minutes IS NULL OR collection_frequency_minutes >= 60), review_notes TEXT, reviewed_at_utc TEXT, last_attempt_at_utc TEXT, last_error TEXT, failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0), consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0), last_content_at_utc TEXT, last_test_at_utc TEXT, last_test_result TEXT NOT NULL DEFAULT 'not_tested'
    CHECK (last_test_result IN ('not_tested','passed','failed')), newest_item_at_utc TEXT, freshness_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (freshness_status IN ('unknown','fresh','stale','not_applicable')), is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    -- a source can only be enabled for collection after its access/terms are verified
    CHECK (enabled = 0 OR access_status = 'verified_permitted')
);

CREATE TABLE story_cluster_members (
    cluster_id         INTEGER NOT NULL REFERENCES story_clusters(cluster_id),
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    similarity         REAL NOT NULL CHECK (similarity BETWEEN 0 AND 1),
    is_near_duplicate  INTEGER NOT NULL CHECK (is_near_duplicate IN (0,1)),
    added_at_utc       TEXT NOT NULL,
    PRIMARY KEY (cluster_id, source_item_id)
);

CREATE TABLE story_clusters (
    cluster_id         INTEGER PRIMARY KEY,
    cluster_key        TEXT NOT NULL UNIQUE,
    event_id           INTEGER REFERENCES events(event_id),
    created_at_utc     TEXT NOT NULL
);

CREATE TABLE user_watchlist (
    watch_id        INTEGER PRIMARY KEY,
    item_type       TEXT NOT NULL CHECK (item_type IN ('ticker','keyword','account','sector','commodity')),
    value           TEXT NOT NULL,
    alert_preferences_json TEXT CHECK (alert_preferences_json IS NULL OR json_valid(alert_preferences_json)),
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at_utc  TEXT NOT NULL,
    UNIQUE (item_type, value)
);

CREATE INDEX ix_collector_runs_source ON collector_runs(source_id, started_at_utc);

CREATE INDEX ix_collector_runs_status ON collector_runs(status, started_at_utc);

CREATE INDEX ix_commodity_date ON commodity_prices(commodity, observation_date);

CREATE INDEX ix_companies_status ON companies(listing_status);

CREATE INDEX ix_aliases_normalized ON company_aliases(alias_normalized);

CREATE UNIQUE INDEX ux_classification_current ON company_classifications(company_id) WHERE valid_to IS NULL;

CREATE INDEX ix_exposures_company ON company_exposures(company_id);

CREATE INDEX ix_exposures_subject ON company_exposures(subject);

CREATE INDEX ix_identifiers_company ON company_identifiers(company_id);

CREATE UNIQUE INDEX ux_identifiers_current ON company_identifiers(id_type, value) WHERE valid_to IS NULL;

CREATE INDEX ix_company_relationships_child ON company_relationships(child_company_id);

CREATE INDEX ix_company_relationships_parent ON company_relationships(parent_company_id);

CREATE INDEX ix_event_companies_company ON event_companies(company_id);

CREATE INDEX ix_evidence_event ON event_evidence(event_id);

CREATE INDEX ix_evidence_source_item ON event_evidence(source_item_id);

CREATE INDEX ix_event_extractions_review ON event_extractions(needs_human_review);

CREATE INDEX ix_events_date ON events(event_date);

CREATE INDEX ix_events_first_seen ON events(first_seen_at_utc);

CREATE INDEX ix_events_stage ON events(status_stage);

CREATE INDEX ix_candidate_evidence_candidate ON exposure_candidate_evidence(candidate_id);

CREATE UNIQUE INDEX ux_candidate_evidence ON exposure_candidate_evidence(
    candidate_id, role, COALESCE(event_evidence_id, 0), COALESCE(company_exposure_id, 0), COALESCE(relationship_id, 0));

CREATE INDEX ix_exposure_candidates_company ON exposure_candidates(company_id);

CREATE INDEX ix_exposure_candidates_event ON exposure_candidates(event_id);

CREATE INDEX ix_exposure_candidates_review ON exposure_candidates(review_status);

CREATE INDEX ix_exposure_reviews_candidate ON exposure_reviews(candidate_id);

CREATE INDEX ix_fin_metrics_company ON financial_metrics(company_id, period_end);

CREATE INDEX ix_impact_inputs_assessment ON impact_assessment_inputs(assessment_id);

CREATE INDEX ix_impact_inputs_candidate ON impact_assessment_inputs(exposure_candidate_id);

CREATE UNIQUE INDEX ux_impact_revisions_review_once ON impact_assessment_revisions(review_id)
WHERE review_id IS NOT NULL;

CREATE INDEX ix_impact_company ON impact_assessments(company_id);

CREATE INDEX ix_impact_status ON impact_assessments(assessment_status);

CREATE INDEX ix_impact_reviews_assessment ON impact_reviews(assessment_id);

CREATE INDEX ix_llm_calls_time ON llm_calls(called_at_utc);

CREATE INDEX ix_market_bar_corrections_bar ON market_bar_corrections(source_id, symbol, timeframe, bar_start_utc);

CREATE INDEX ix_market_bars_symbol ON market_bars(symbol, timeframe, bar_start_utc);

CREATE UNIQUE INDEX ux_media_accounts_handle ON media_accounts(platform, handle) WHERE handle IS NOT NULL;

CREATE INDEX ix_media_items_published ON media_items(published_at_utc);

CREATE INDEX ix_media_metrics_item ON media_metrics_history(media_item_id, observed_at_utc);

CREATE INDEX ix_source_items_collected ON source_items(collected_at_utc);

CREATE INDEX ix_source_items_event_date ON source_items(event_date);

CREATE INDEX ix_source_items_hash ON source_items(content_sha256);

CREATE INDEX ix_source_items_published ON source_items(published_at_utc);

CREATE INDEX ix_source_items_run ON source_items(collection_run_id);

CREATE INDEX ix_story_cluster_members_item ON story_cluster_members(source_item_id);

CREATE VIEW current_company_relationships AS
SELECT r.* FROM company_relationships r
WHERE NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = r.relationship_id);

CREATE VIEW exposure_candidates_current AS
SELECT c.*,
       CASE WHEN EXISTS (SELECT 1 FROM invalid_candidate_evidence v WHERE v.candidate_id = c.candidate_id)
            THEN 0 ELSE 1 END AS evidence_currently_valid,
       CASE WHEN c.evidence_status IN ('potential','strongly_supported','confirmed')
             AND EXISTS (SELECT 1 FROM invalid_candidate_evidence v WHERE v.candidate_id = c.candidate_id)
            THEN 'needs_revalidation' ELSE c.evidence_status END AS effective_status,
       CASE WHEN c.is_synthetic = 1 THEN 'SYNTHETIC TEST DATA' ELSE 'real' END AS data_label
FROM exposure_candidates c;

CREATE VIEW impact_assessments_current AS
SELECT a.*,
       CASE WHEN a.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review') THEN a.assessment_status
            WHEN EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = a.assessment_id)
              THEN 'needs_revalidation'
            WHEN a.assessment_status = 'provisional' AND EXISTS (
                 SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
                   ON c.candidate_id = i.exposure_candidate_id
                 WHERE i.assessment_id = a.assessment_id AND i.exposure_candidate_id IS NOT NULL
                   AND (c.effective_status IS NULL OR c.effective_status NOT IN ('strongly_supported','confirmed')))
              THEN 'needs_revalidation'
            WHEN a.assessment_status = 'confirmed_conclusion' AND EXISTS (
                 SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
                   ON c.candidate_id = i.exposure_candidate_id
                 WHERE i.assessment_id = a.assessment_id AND i.exposure_candidate_id IS NOT NULL
                   AND (c.effective_status IS NULL OR c.effective_status <> 'confirmed'))
              THEN 'needs_revalidation'
            WHEN a.assessment_status IN ('provisional','confirmed_conclusion')
                 AND (a.freshness_basis <> 'explicit_source_expiry' OR NOT EXISTS (
                      SELECT 1 FROM impact_explicit_freshness f WHERE f.assessment_id = a.assessment_id))
              THEN 'needs_revalidation'
            ELSE a.assessment_status END AS effective_status,
       CASE WHEN EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = a.assessment_id)
            THEN 0 ELSE 1 END AS inputs_currently_valid,
       CASE WHEN a.is_synthetic = 1 THEN 'SYNTHETIC TEST DATA' ELSE 'real' END AS data_label
FROM impact_assessments a;

CREATE VIEW impact_event_company_eligibility AS
WITH ev AS (
    SELECT e.event_id,
           CASE WHEN e.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN e.event_date END AS d
    FROM events e
), cls AS (
    SELECT ev.event_id, cc.company_id, cc.sector_id,
           CASE WHEN ev.d IS NULL THEN 'current_classification' ELSE 'event_date_classification' END AS basis,
           ev.d
    FROM ev JOIN company_classifications cc
      ON (ev.d IS NULL AND cc.valid_to IS NULL)
      OR (ev.d IS NOT NULL AND (cc.valid_from IS NULL OR cc.valid_from <= ev.d)
          AND (cc.valid_to IS NULL OR cc.valid_to >= ev.d))
)
SELECT cls.event_id, cls.company_id, cls.sector_id, cls.basis AS eligibility_basis,
       CASE
         WHEN cls.d IS NULL THEN CASE c.listing_status WHEN 'listed' THEN 'listed' WHEN 'suspended' THEN 'suspended'
                                     WHEN 'delisted' THEN 'not_listed' ELSE 'unknown' END
         ELSE COALESCE(
           (SELECT CASE h.status WHEN 'listed' THEN 'listed' WHEN 'suspended' THEN 'suspended'
                                 ELSE 'not_listed' END
            FROM company_status_history h
            WHERE h.company_id = cls.company_id AND h.effective_date IS NOT NULL AND h.effective_date <= cls.d
              AND h.status IN ('listed','suspended','delisted','merged_into')
            ORDER BY h.effective_date DESC, h.status_event_id DESC LIMIT 1),
           CASE WHEN c.listing_status = 'listed' AND NOT EXISTS (
                       SELECT 1 FROM company_status_history h2 WHERE h2.company_id = cls.company_id)
                THEN 'listed' ELSE 'unknown' END)
       END AS listing_at_event
FROM cls JOIN companies c ON c.company_id = cls.company_id;

CREATE VIEW impact_expiry_policies_current AS
SELECT v.policy_version,
       a.effective_from_utc, r.effective_to_utc, a.actor AS approved_by,
       CASE WHEN a.policy_event_id IS NULL THEN 'draft'
            WHEN r.policy_event_id IS NULL THEN 'approved' ELSE 'retired' END AS status
FROM impact_expiry_policy_versions v
LEFT JOIN impact_expiry_policy_events a ON a.policy_version = v.policy_version AND a.event_type = 'approved'
LEFT JOIN impact_expiry_policy_events r ON r.policy_version = v.policy_version AND r.event_type = 'retired';

CREATE VIEW impact_expiry_policy_overlaps AS
SELECT x.policy_version AS version_a, y.policy_version AS version_b
FROM impact_expiry_policies_current x JOIN impact_expiry_policies_current y
  ON x.policy_version < y.policy_version
WHERE x.status <> 'draft' AND y.status <> 'draft'
  AND x.effective_from_utc < COALESCE(y.effective_to_utc, '9999-12-31T23:59:59Z')
  AND y.effective_from_utc < COALESCE(x.effective_to_utc, '9999-12-31T23:59:59Z');

CREATE VIEW impact_explicit_freshness AS
SELECT f.assessment_id
FROM impact_linked_exposure_freshness f
GROUP BY f.assessment_id
HAVING SUM(f.freshness <> 'fresh') = 0;

CREATE VIEW impact_invalid_inputs AS
SELECT i.input_id, i.assessment_id, i.input_kind,
       CASE
         WHEN NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
                   AND s.access_status = 'verified_permitted' AND s.enabled = 1) THEN 'source_restricted'
         WHEN i.event_evidence_id IS NOT NULL AND EXISTS (SELECT 1 FROM evidence_retractions x
              WHERE x.record_table = 'event_evidence' AND x.record_id = i.event_evidence_id) THEN 'evidence_retracted'
         WHEN i.exposure_candidate_id IS NOT NULL AND (cv.evidence_currently_valid = 0
              OR cv.effective_status IN ('rejected','needs_revalidation')) THEN 'evidence_revoked'
         WHEN i.exposure_candidate_id IS NOT NULL AND EXISTS (
              SELECT 1 FROM exposure_candidate_revisions nr JOIN exposure_candidate_revisions lr
                ON lr.candidate_id = nr.candidate_id AND lr.revision_no = i.exposure_candidate_revision
              WHERE nr.candidate_id = i.exposure_candidate_id AND nr.revision_no > i.exposure_candidate_revision
                AND (nr.evidence_status <> lr.evidence_status
                     OR json_extract(nr.snapshot_json, '$.impact_direction')
                        IS NOT json_extract(lr.snapshot_json, '$.impact_direction'))) THEN 'evidence_superseded'
       END AS invalid_reason
FROM impact_assessment_inputs i
JOIN source_items si ON si.source_item_id = i.source_item_id
JOIN sources s ON s.source_id = si.source_id
LEFT JOIN exposure_candidates_current cv ON cv.candidate_id = i.exposure_candidate_id
WHERE NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
           AND s.access_status = 'verified_permitted' AND s.enabled = 1)
   OR (i.event_evidence_id IS NOT NULL AND EXISTS (SELECT 1 FROM evidence_retractions x
       WHERE x.record_table = 'event_evidence' AND x.record_id = i.event_evidence_id))
   OR (i.exposure_candidate_id IS NOT NULL AND (cv.evidence_currently_valid = 0
       OR cv.effective_status IN ('rejected','needs_revalidation')))
   OR (i.exposure_candidate_id IS NOT NULL AND EXISTS (
       SELECT 1 FROM exposure_candidate_revisions nr JOIN exposure_candidate_revisions lr
         ON lr.candidate_id = nr.candidate_id AND lr.revision_no = i.exposure_candidate_revision
       WHERE nr.candidate_id = i.exposure_candidate_id AND nr.revision_no > i.exposure_candidate_revision
         AND (nr.evidence_status <> lr.evidence_status
              OR json_extract(nr.snapshot_json, '$.impact_direction')
                 IS NOT json_extract(lr.snapshot_json, '$.impact_direction'))));

CREATE VIEW impact_linked_exposure_freshness AS
SELECT i.assessment_id, x.exposure_id, x.valid_to,
       CASE
         WHEN x.valid_to IS NULL THEN 'missing'
         WHEN NOT ((length(x.valid_to) = 10 AND x.valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                    AND date(x.valid_to) IS x.valid_to)
                OR (length(x.valid_to) = 20
                    AND x.valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                    AND strftime('%Y-%m-%dT%H:%M:%SZ', x.valid_to) IS x.valid_to)) THEN 'invalid'
         WHEN substr(x.valid_to, 1, 10) < date('now') THEN 'expired'
         ELSE 'fresh'
       END AS freshness
FROM impact_assessment_inputs i
JOIN exposure_candidate_evidence l ON l.candidate_id = i.exposure_candidate_id AND l.role = 'company_specific'
JOIN company_exposures x ON x.exposure_id = l.company_exposure_id;

CREATE VIEW impact_sector_aggregates_current AS
WITH combos AS (
    SELECT DISTINCT g.sector_id, a.event_id, a.mechanism_id, a.scenario_kind, a.transmission_version,
                    g.eligibility_basis
    FROM impact_assessments a JOIN impact_event_company_eligibility g
      ON g.event_id = a.event_id AND g.company_id = a.company_id
), members AS (
    SELECT k.*, g.company_id, g.listing_at_event,
           x.assessment_id, x.effective_status, x.direction, x.is_synthetic,
           CASE
             WHEN g.listing_at_event = 'not_listed' THEN 'not_listed_at_event_date'
             WHEN g.listing_at_event = 'suspended' THEN 'suspended_at_event_date'
             WHEN g.listing_at_event = 'unknown' THEN 'listing_status_unknown'
             WHEN x.assessment_id IS NULL THEN 'no_assessment'
             WHEN x.effective_status = 'needs_review' THEN 'assessment_needs_review'
             WHEN x.effective_status = 'needs_revalidation' THEN 'assessment_needs_revalidation'
             WHEN x.effective_status = 'withdrawn_evidence_invalid' THEN 'assessment_withdrawn'
             WHEN x.effective_status = 'rejected_by_review' THEN 'assessment_rejected'
           END AS exclusion_reason
    FROM combos k
    JOIN impact_event_company_eligibility g ON g.event_id = k.event_id AND g.sector_id = k.sector_id
    LEFT JOIN impact_assessments_current x
      ON x.event_id = k.event_id AND x.company_id = g.company_id AND x.mechanism_id = k.mechanism_id
     AND x.scenario_kind = k.scenario_kind AND x.transmission_version = k.transmission_version
), agg AS (
    SELECT sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis,
           SUM(listing_at_event <> 'not_listed') AS eligible_n,
           SUM(listing_at_event <> 'not_listed' AND assessment_id IS NOT NULL
               AND effective_status IN ('scenario_only','provisional','confirmed_conclusion')) AS assessed_valid_n,
           SUM(listing_at_event <> 'not_listed'
               AND effective_status IN ('needs_review','needs_revalidation')) AS assessed_review_n,
           SUM(listing_at_event <> 'not_listed'
               AND effective_status IN ('withdrawn_evidence_invalid','rejected_by_review')) AS assessed_terminal_n,
           SUM(listing_at_event <> 'not_listed' AND assessment_id IS NULL) AS unassessed_n,
           SUM(listing_at_event = 'suspended') AS suspended_n,
           SUM(listing_at_event = 'unknown') AS eligibility_uncertain_n,
           SUM(exclusion_reason IS NULL AND direction = 'positive') AS positive_n,
           SUM(exclusion_reason IS NULL AND direction = 'negative') AS negative_n,
           SUM(exclusion_reason IS NULL AND direction = 'mixed') AS mixed_n,
           SUM(exclusion_reason IS NULL AND direction = 'neutral') AS neutral_n,
           SUM(exclusion_reason IS NULL AND direction = 'unknown') AS unknown_n,
           SUM(exclusion_reason IS NULL) AS directional_n,
           SUM(exclusion_reason IS NULL AND effective_status = 'scenario_only') AS scenario_only_n,
           SUM(exclusion_reason IS NULL AND effective_status IN ('provisional','confirmed_conclusion'))
               AS evidence_backed_n,
           MIN(CASE WHEN exclusion_reason IS NULL THEN CASE effective_status
                    WHEN 'scenario_only' THEN 1 WHEN 'provisional' THEN 2 WHEN 'confirmed_conclusion' THEN 3 END
               END) AS weakest_rank,
           MAX(COALESCE(is_synthetic, 0)) AS is_synthetic,
           json_group_array(CASE WHEN exclusion_reason IS NULL THEN json_object('company_id', company_id,
               'assessment_id', assessment_id, 'effective_status', effective_status, 'direction', direction)
               END) AS included_raw,
           json_group_array(CASE WHEN exclusion_reason IS NOT NULL THEN json_object('company_id', company_id,
               'reason', exclusion_reason, 'listing_at_event', listing_at_event,
               'assessment_id', assessment_id, 'effective_status', effective_status) END) AS excluded_raw
    FROM members
    GROUP BY sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis
)
SELECT sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis,
       eligible_n, assessed_valid_n, assessed_review_n, assessed_terminal_n, unassessed_n,
       suspended_n, eligibility_uncertain_n,
       CASE WHEN eligible_n > 0 THEN ROUND(100.0 * assessed_valid_n / eligible_n, 1) END AS coverage_pct,
       CASE WHEN eligible_n > 0 AND assessed_valid_n = eligible_n AND suspended_n = 0
                 AND eligibility_uncertain_n = 0 THEN 'complete' ELSE 'partial' END AS completeness,
       positive_n, negative_n, mixed_n, neutral_n, unknown_n,
       scenario_only_n, evidence_backed_n,
       CASE weakest_rank WHEN 1 THEN 'scenario_only' WHEN 2 THEN 'provisional'
            WHEN 3 THEN 'confirmed_conclusion' END AS weakest_status,
       CASE WHEN directional_n = 0 THEN 'unknown'
            WHEN positive_n = directional_n THEN 'positive'
            WHEN negative_n = directional_n THEN 'negative'
            WHEN neutral_n = directional_n THEN 'neutral'
            WHEN unknown_n > 0 AND (positive_n + unknown_n = directional_n OR negative_n + unknown_n = directional_n
                                    OR neutral_n + unknown_n = directional_n) THEN 'unknown'
            ELSE 'mixed' END AS direction_among_assessed,
       CASE WHEN NOT (eligible_n > 0 AND assessed_valid_n = eligible_n AND suspended_n = 0
                      AND eligibility_uncertain_n = 0) THEN 'not_concluded_partial_coverage'
            WHEN scenario_only_n > 0 THEN 'not_concluded_scenario_only_components'
            ELSE CASE WHEN directional_n = 0 THEN 'unknown'
                      WHEN positive_n = directional_n THEN 'positive'
                      WHEN negative_n = directional_n THEN 'negative'
                      WHEN neutral_n = directional_n THEN 'neutral'
                      WHEN unknown_n > 0 AND (positive_n + unknown_n = directional_n
                                              OR negative_n + unknown_n = directional_n
                                              OR neutral_n + unknown_n = directional_n) THEN 'unknown'
                      ELSE 'mixed' END
       END AS sector_conclusion,
       (SELECT json_group_array(json(value)) FROM json_each(included_raw) WHERE value IS NOT NULL) AS included_json,
       (SELECT json_group_array(json(value)) FROM json_each(excluded_raw) WHERE value IS NOT NULL) AS excluded_json,
       is_synthetic,
       CASE WHEN is_synthetic = 1 THEN 'SYNTHETIC TEST DATA' ELSE 'real' END AS data_label
FROM agg;

CREATE VIEW impact_unclassified_companies AS
SELECT DISTINCT a.event_id, a.company_id, 'no_sector_classification' AS reason
FROM impact_assessments a
WHERE NOT EXISTS (SELECT 1 FROM impact_event_company_eligibility g
                  WHERE g.event_id = a.event_id AND g.company_id = a.company_id);

CREATE VIEW invalid_candidate_evidence AS
SELECT l.candidate_id, l.role, l.event_evidence_id, l.company_exposure_id, l.relationship_id, l.source_item_id
FROM exposure_candidate_evidence l
JOIN source_items i ON i.source_item_id = l.source_item_id
JOIN sources s ON s.source_id = i.source_id
WHERE l.role = 'company_specific' AND (
       NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
            AND s.access_status = 'verified_permitted' AND s.enabled = 1)
    OR EXISTS (SELECT 1 FROM evidence_retractions x WHERE x.record_table = 'event_evidence'
               AND x.record_id = l.event_evidence_id)
    OR EXISTS (SELECT 1 FROM evidence_retractions x WHERE x.record_table = 'company_exposures'
               AND x.record_id = l.company_exposure_id)
    OR (l.relationship_id IS NOT NULL AND (
            EXISTS (SELECT 1 FROM company_relationships r WHERE r.supersedes_relationship_id = l.relationship_id)
         OR EXISTS (SELECT 1 FROM company_relationships r WHERE r.relationship_id = l.relationship_id
                    AND r.evidence_status = 'rejected'))));

CREATE VIEW market_bars_current AS
SELECT b.source_id, b.symbol, b.timeframe, b.bar_start_utc, b.session_date_pkt,
       COALESCE(c.open, b.open) AS open, COALESCE(c.high, b.high) AS high,
       COALESCE(c.low, b.low) AS low, COALESCE(c.close, b.close) AS close,
       COALESCE(c.volume, b.volume) AS volume,
       b.retrieved_at_utc AS first_retrieved_at_utc,
       COALESCE(c.retrieved_at_utc, b.retrieved_at_utc) AS last_retrieved_at_utc,
       (SELECT COUNT(*) FROM market_bar_corrections x WHERE x.source_id = b.source_id AND x.symbol = b.symbol
          AND x.timeframe = b.timeframe AND x.bar_start_utc = b.bar_start_utc) AS correction_count
FROM market_bars b
LEFT JOIN market_bar_corrections c ON c.correction_id = (
    SELECT MAX(x.correction_id) FROM market_bar_corrections x WHERE x.source_id = b.source_id
       AND x.symbol = b.symbol AND x.timeframe = b.timeframe AND x.bar_start_utc = b.bar_start_utc);

CREATE VIEW market_coverage AS
SELECT source_id, symbol, timeframe, COUNT(*) AS bars, MIN(bar_start_utc) AS first_bar_utc,
       MAX(bar_start_utc) AS last_bar_utc, MAX(retrieved_at_utc) AS last_retrieved_at_utc,
       COUNT(DISTINCT session_date_pkt) AS sessions
FROM market_bars GROUP BY source_id, symbol, timeframe;

CREATE VIEW source_health AS
SELECT s.source_id,
       s.lifecycle_status,
       s.last_attempt_at_utc,
       s.last_success_at_utc,
       s.last_error,
       s.consecutive_failures,
       s.failure_count,
       s.last_content_at_utc,
       s.last_test_at_utc,
       s.last_test_result,
       s.newest_item_at_utc,
       s.freshness_status,
       COUNT(r.run_id)                                          AS runs,
       SUM(CASE WHEN r.status = 'succeeded' THEN 1 ELSE 0 END)  AS runs_succeeded,
       SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END)     AS runs_failed,
       ROUND(AVG(r.duration_ms))                                AS avg_duration_ms,
       SUM(r.items_accepted)                                    AS items_new,
       SUM(r.items_duplicate)                                   AS items_duplicate,
       SUM(r.items_new_version)                                 AS items_new_version,
       SUM(r.items_failed)                                      AS items_failed,
       MAX(CASE WHEN r.status = 'failed' THEN r.started_at_utc END) AS last_failed_run_utc
FROM sources s LEFT JOIN collector_runs r ON r.source_id = s.source_id AND r.status <> 'dry_run'
GROUP BY s.source_id;

CREATE TRIGGER trg_alerts_no_delete BEFORE DELETE ON alerts_predictions
BEGIN SELECT RAISE(ABORT, 'alerts_predictions are frozen point-in-time records'); END;

CREATE TRIGGER trg_alerts_no_update BEFORE UPDATE ON alerts_predictions
BEGIN SELECT RAISE(ABORT, 'alerts_predictions are frozen point-in-time records'); END;

CREATE TRIGGER trg_analyses_no_delete BEFORE DELETE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are versioned records and cannot be deleted'); END;

CREATE TRIGGER trg_analyses_no_update BEFORE UPDATE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are versioned; insert a new analysis_version'); END;

CREATE TRIGGER trg_company_exposures_linked_immutable BEFORE UPDATE ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l
             WHERE l.company_exposure_id IN (OLD.exposure_id, NEW.exposure_id))
 AND (NEW.exposure_id IS NOT OLD.exposure_id OR NEW.valid_to IS NOT OLD.valid_to
      OR NEW.valid_from IS NOT OLD.valid_from OR NEW.company_id IS NOT OLD.company_id
      OR NEW.exposure_kind IS NOT OLD.exposure_kind OR NEW.subject IS NOT OLD.subject
      OR NEW.confidence IS NOT OLD.confidence OR NEW.source_item_id IS NOT OLD.source_item_id
      OR NEW.evidence_excerpt IS NOT OLD.evidence_excerpt OR NEW.last_verified_utc IS NOT OLD.last_verified_utc
      OR NEW.segment_id IS NOT OLD.segment_id OR NEW.scope IS NOT OLD.scope)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate is immutable; retract it and record a new exposure'); END;

CREATE TRIGGER trg_company_exposures_linked_no_delete BEFORE DELETE ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l WHERE l.company_exposure_id = OLD.exposure_id)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate cannot be deleted'); END;

CREATE TRIGGER trg_company_exposures_linked_no_replace BEFORE INSERT ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l WHERE l.company_exposure_id = NEW.exposure_id)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate cannot be replaced'); END;

CREATE TRIGGER trg_relationships_no_delete BEFORE DELETE ON company_relationships
BEGIN SELECT RAISE(ABORT, 'company_relationships are append-only; insert a superseding row'); END;

CREATE TRIGGER trg_relationships_no_update BEFORE UPDATE ON company_relationships
BEGIN SELECT RAISE(ABORT, 'company_relationships are append-only; insert a superseding row'); END;

CREATE TRIGGER trg_relationships_validate BEFORE INSERT ON company_relationships
BEGIN
    -- a correction must describe the same parent and child as the row it supersedes
    SELECT RAISE(ABORT, 'superseding row must keep the same parent and child')
    WHERE NEW.supersedes_relationship_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_relationships o WHERE o.relationship_id = NEW.supersedes_relationship_id
          AND o.parent_company_id = NEW.parent_company_id AND o.child_name = NEW.child_name
          AND o.child_company_id IS NEW.child_company_id);
    -- a new (non-correction) row may not duplicate a current relationship
    SELECT RAISE(ABORT, 'relationship already recorded; supersede it instead')
    WHERE NEW.supersedes_relationship_id IS NULL AND EXISTS (
        SELECT 1 FROM company_relationships o
        WHERE o.parent_company_id = NEW.parent_company_id AND o.child_name = NEW.child_name
          AND o.relationship_type = NEW.relationship_type
          AND NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = o.relationship_id));
    -- direct reversal cycle (A parent of B and B parent of A); deeper cycles are refused in application code
    SELECT RAISE(ABORT, 'relationship would create a cycle')
    WHERE NEW.child_company_id IS NOT NULL AND NEW.evidence_status <> 'rejected' AND EXISTS (
        SELECT 1 FROM company_relationships o
        WHERE o.parent_company_id = NEW.child_company_id AND o.child_company_id = NEW.parent_company_id
          AND o.evidence_status <> 'rejected'
          AND NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = o.relationship_id));
    -- stronger statuses need evidence from an approved source; synthetic evidence only on synthetic rows
    SELECT RAISE(ABORT, 'relationship evidence must come from an approved (ACTIVE) source')
    WHERE NEW.evidence_status IN ('confirmed','strongly_supported') AND NOT EXISTS (
        SELECT 1 FROM source_items i JOIN sources s USING(source_id)
        WHERE i.source_item_id = NEW.source_item_id AND s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
          AND s.access_status = 'verified_permitted' AND s.enabled = 1);
    SELECT RAISE(ABORT, 'synthetic evidence can only support a synthetic relationship')
    WHERE NEW.is_synthetic = 0 AND EXISTS (
        SELECT 1 FROM source_items i JOIN sources s USING(source_id)
        WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1);
END;

CREATE TRIGGER trg_status_history_no_delete BEFORE DELETE ON company_status_history
BEGIN SELECT RAISE(ABORT, 'company_status_history is append-only'); END;

CREATE TRIGGER trg_status_history_no_update BEFORE UPDATE ON company_status_history
BEGIN SELECT RAISE(ABORT, 'company_status_history is append-only'); END;

CREATE TRIGGER trg_event_companies_accept_update BEFORE UPDATE OF reviewer_status ON event_companies
WHEN NEW.reviewer_status = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM exposure_candidates c WHERE c.event_id = NEW.event_id AND c.company_id = NEW.company_id
      AND c.evidence_status = 'confirmed')
BEGIN SELECT RAISE(ABORT, 'accepted event-company links require a confirmed exposure candidate'); END;

CREATE TRIGGER trg_event_companies_accepted_requires_confirmed BEFORE INSERT ON event_companies
WHEN NEW.reviewer_status = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM exposure_candidates c WHERE c.event_id = NEW.event_id AND c.company_id = NEW.company_id
      AND c.evidence_status = 'confirmed')
BEGIN SELECT RAISE(ABORT, 'accepted event-company links require a confirmed exposure candidate'); END;

CREATE TRIGGER trg_evidence_no_delete BEFORE DELETE ON event_evidence
BEGIN SELECT RAISE(ABORT, 'event_evidence is append-only'); END;

CREATE TRIGGER trg_evidence_no_update BEFORE UPDATE ON event_evidence
BEGIN SELECT RAISE(ABORT, 'event_evidence is append-only; add a new evidence row'); END;

CREATE TRIGGER trg_event_extractions_no_delete BEFORE DELETE ON event_extractions
BEGIN SELECT RAISE(ABORT, 'event_extractions are append-only'); END;

CREATE TRIGGER trg_event_extractions_no_update BEFORE UPDATE ON event_extractions
BEGIN SELECT RAISE(ABORT, 'event_extractions are append-only'); END;

CREATE TRIGGER trg_event_revisions_no_delete BEFORE DELETE ON event_revisions
BEGIN SELECT RAISE(ABORT, 'event_revisions are append-only'); END;

CREATE TRIGGER trg_event_revisions_no_update BEFORE UPDATE ON event_revisions
BEGIN SELECT RAISE(ABORT, 'event_revisions are append-only'); END;

CREATE TRIGGER trg_events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events cannot be deleted; record a revision instead'); END;

CREATE TRIGGER trg_events_refutation_withdraws_assessments AFTER UPDATE OF verification_state ON events
WHEN NEW.verification_state = 'refuted' AND OLD.verification_state <> 'refuted'
BEGIN
    UPDATE impact_assessments
       SET assessment_status = 'withdrawn_evidence_invalid', status_reason = 'event_refuted',
           actor_type = 'system', changed_by = 'system:event_refutation',
           change_reason = 'event refuted (event revision ' || NEW.current_revision || ')',
           current_revision = current_revision + 1,
           updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
     WHERE event_id = NEW.event_id AND scenario_kind = 'current'
       AND assessment_status NOT IN ('withdrawn_evidence_invalid','rejected_by_review');
END;

CREATE TRIGGER trg_events_require_revision BEFORE UPDATE ON events
WHEN NEW.current_revision <> OLD.current_revision + 1
  OR NOT EXISTS (SELECT 1 FROM event_revisions r
                 WHERE r.event_id = NEW.event_id AND r.revision_no = NEW.current_revision)
BEGIN SELECT RAISE(ABORT, 'update events only through a new recorded revision'); END;

CREATE TRIGGER trg_evidence_retractions_no_replace BEFORE INSERT ON evidence_retractions
WHEN EXISTS (SELECT 1 FROM evidence_retractions r
             WHERE r.retraction_id = NEW.retraction_id
                OR (r.record_table = NEW.record_table AND r.record_id = NEW.record_id))
BEGIN SELECT RAISE(ABORT, 'evidence_retractions: a retraction already exists for this id or record; retractions are permanent'); END;

CREATE TRIGGER trg_retractions_no_delete BEFORE DELETE ON evidence_retractions
BEGIN SELECT RAISE(ABORT, 'evidence_retractions are append-only'); END;

CREATE TRIGGER trg_retractions_no_update BEFORE UPDATE ON evidence_retractions
BEGIN SELECT RAISE(ABORT, 'evidence_retractions are append-only'); END;

CREATE TRIGGER trg_retractions_target_exists BEFORE INSERT ON evidence_retractions
WHEN (NEW.record_table = 'event_evidence'
      AND NOT EXISTS (SELECT 1 FROM event_evidence WHERE evidence_id = NEW.record_id))
  OR (NEW.record_table = 'company_exposures'
      AND NOT EXISTS (SELECT 1 FROM company_exposures WHERE exposure_id = NEW.record_id))
BEGIN SELECT RAISE(ABORT, 'retraction must refer to an existing evidence record'); END;

CREATE TRIGGER trg_candidate_evidence_no_delete BEFORE DELETE ON exposure_candidate_evidence
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_evidence is append-only'); END;

CREATE TRIGGER trg_candidate_evidence_no_update BEFORE UPDATE ON exposure_candidate_evidence
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_evidence is append-only'); END;

CREATE TRIGGER trg_candidate_evidence_validate BEFORE INSERT ON exposure_candidate_evidence
BEGIN
    SELECT RAISE(ABORT, 'event evidence must belong to the candidate''s event and source item')
    WHERE NEW.event_evidence_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM event_evidence e JOIN exposure_candidates c ON c.event_id = e.event_id
        WHERE e.evidence_id = NEW.event_evidence_id AND c.candidate_id = NEW.candidate_id
          AND e.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'company exposure evidence must belong to the candidate''s company and source item')
    WHERE NEW.company_exposure_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_exposures x JOIN exposure_candidates c ON c.company_id = x.company_id
        WHERE x.exposure_id = NEW.company_exposure_id AND c.candidate_id = NEW.candidate_id
          AND x.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'relationship evidence must name the candidate''s company as parent')
    WHERE NEW.relationship_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_relationships r JOIN exposure_candidates c ON c.company_id = r.parent_company_id
        WHERE r.relationship_id = NEW.relationship_id AND c.candidate_id = NEW.candidate_id
          AND r.source_item_id IS NEW.source_item_id);
    SELECT RAISE(ABORT, 'synthetic evidence can only support a synthetic candidate')
    WHERE EXISTS (SELECT 1 FROM source_items i JOIN sources s USING(source_id)
                  JOIN exposure_candidates c ON c.candidate_id = NEW.candidate_id
                  WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1 AND c.is_synthetic = 0);
    SELECT RAISE(ABORT, 'a synthetic relationship can only support a synthetic candidate')
    WHERE NEW.relationship_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM company_relationships r JOIN exposure_candidates c ON c.candidate_id = NEW.candidate_id
        WHERE r.relationship_id = NEW.relationship_id AND r.is_synthetic = 1 AND c.is_synthetic = 0);
    SELECT RAISE(ABORT, 'evidence cannot be added to a confirmed or rejected candidate')
    WHERE EXISTS (SELECT 1 FROM exposure_candidates c WHERE c.candidate_id = NEW.candidate_id
                  AND c.evidence_status IN ('confirmed','rejected'));
END;

CREATE TRIGGER trg_exposure_candidate_evidence_no_replace BEFORE INSERT ON exposure_candidate_evidence
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l
             WHERE l.rowid = NEW.rowid
                OR (l.candidate_id = NEW.candidate_id AND l.role = NEW.role
                    AND COALESCE(l.event_evidence_id, 0) = COALESCE(NEW.event_evidence_id, 0)
                    AND COALESCE(l.company_exposure_id, 0) = COALESCE(NEW.company_exposure_id, 0)
                    AND COALESCE(l.relationship_id, 0) = COALESCE(NEW.relationship_id, 0)))
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_evidence: duplicate key; existing evidence links cannot be replaced'); END;

CREATE TRIGGER trg_exposure_candidate_revisions_no_replace BEFORE INSERT ON exposure_candidate_revisions
WHEN EXISTS (SELECT 1 FROM exposure_candidate_revisions r
             WHERE r.candidate_id = NEW.candidate_id AND r.revision_no = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions: duplicate key; existing revisions cannot be replaced'); END;

CREATE TRIGGER trg_exposure_revisions_no_delete BEFORE DELETE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;

CREATE TRIGGER trg_exposure_revisions_no_update BEFORE UPDATE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;

CREATE TRIGGER trg_exposure_revisions_only_current BEFORE INSERT ON exposure_candidate_revisions
WHEN NOT EXISTS (SELECT 1 FROM exposure_candidates c
                 WHERE c.candidate_id = NEW.candidate_id AND c.current_revision = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'revisions are written by triggers for the current revision only'); END;

CREATE TRIGGER trg_exposure_candidates_insert BEFORE INSERT ON exposure_candidates
BEGIN
    SELECT RAISE(ABORT, 'candidates start at revision 1')
    WHERE NEW.current_revision <> 1;
    SELECT RAISE(ABORT, 'candidates are created unverified or rejected; stronger statuses need linked evidence')
    WHERE NEW.evidence_status NOT IN ('unverified','rejected');
    SELECT RAISE(ABORT, 'a new candidate cannot carry a review decision')
    WHERE NEW.last_review_id IS NOT NULL OR NEW.review_status IN ('accepted');
END;

CREATE TRIGGER trg_exposure_candidates_no_delete BEFORE DELETE ON exposure_candidates
BEGIN SELECT RAISE(ABORT, 'exposure candidates cannot be deleted; record a rejection instead'); END;

CREATE TRIGGER trg_exposure_candidates_no_replace BEFORE INSERT ON exposure_candidates
WHEN EXISTS (SELECT 1 FROM exposure_candidates c
             WHERE c.candidate_id = NEW.candidate_id
                OR (c.event_id = NEW.event_id AND c.company_id = NEW.company_id
                    AND c.exposure_category = NEW.exposure_category AND c.exposure_subtype = NEW.exposure_subtype
                    AND c.mechanism = NEW.mechanism AND c.ruleset_version = NEW.ruleset_version))
BEGIN SELECT RAISE(ABORT, 'exposure_candidates: duplicate key; existing candidates cannot be replaced'); END;

CREATE TRIGGER trg_exposure_candidates_rev1 AFTER INSERT ON exposure_candidates
BEGIN
    INSERT INTO exposure_candidate_revisions(candidate_id, revision_no, recorded_at_utc, evidence_status,
        review_status, last_review_id, snapshot_json, change_reason, changed_by)
    VALUES (NEW.candidate_id, 1, NEW.created_at_utc, NEW.evidence_status, NEW.review_status, NULL,
        json_object('impact_direction', NEW.impact_direction, 'exposure_level', NEW.exposure_level,
                    'evidence_status', NEW.evidence_status, 'review_status', NEW.review_status,
                    'confidence', NEW.confidence, 'explanation', NEW.explanation,
                    'missing_evidence', json(NEW.missing_evidence_json),
                    'review_reasons', json(NEW.review_reasons_json), 'segment_id', NEW.segment_id),
        NEW.change_reason, NEW.changed_by);
END;

CREATE TRIGGER trg_exposure_candidates_revision AFTER UPDATE ON exposure_candidates
BEGIN
    INSERT INTO exposure_candidate_revisions(candidate_id, revision_no, recorded_at_utc, evidence_status,
        review_status, last_review_id, snapshot_json, change_reason, changed_by)
    VALUES (NEW.candidate_id, NEW.current_revision, NEW.updated_at_utc, NEW.evidence_status, NEW.review_status,
        NEW.last_review_id,
        json_object('impact_direction', NEW.impact_direction, 'exposure_level', NEW.exposure_level,
                    'evidence_status', NEW.evidence_status, 'review_status', NEW.review_status,
                    'confidence', NEW.confidence, 'explanation', NEW.explanation,
                    'missing_evidence', json(NEW.missing_evidence_json),
                    'review_reasons', json(NEW.review_reasons_json), 'segment_id', NEW.segment_id),
        NEW.change_reason, NEW.changed_by);
END;

CREATE TRIGGER trg_exposure_candidates_update BEFORE UPDATE ON exposure_candidates
BEGIN
    SELECT RAISE(ABORT, 'each update must move to the next revision')
    WHERE NEW.current_revision <> OLD.current_revision + 1;
    SELECT RAISE(ABORT, 'candidate identity cannot change')
    WHERE NEW.event_id <> OLD.event_id OR NEW.company_id <> OLD.company_id
       OR NEW.exposure_category <> OLD.exposure_category OR NEW.exposure_subtype <> OLD.exposure_subtype
       OR NEW.mechanism <> OLD.mechanism OR NEW.origin <> OLD.origin
       OR NEW.ruleset_version <> OLD.ruleset_version OR NEW.is_synthetic <> OLD.is_synthetic
       OR NEW.created_at_utc <> OLD.created_at_utc;
    SELECT RAISE(ABORT, 'a confirmed or rejected decision can only change through a new review')
    WHERE OLD.review_status IN ('accepted','rejected') AND NEW.last_review_id IS OLD.last_review_id;
    -- potential and above: company-specific evidence must be linked, and all of it from approved sources
    SELECT RAISE(ABORT, 'potential or stronger status requires linked company-specific evidence')
    WHERE NEW.evidence_status IN ('potential','strongly_supported','confirmed') AND NOT EXISTS (
        SELECT 1 FROM exposure_candidate_evidence l WHERE l.candidate_id = NEW.candidate_id
          AND l.role = 'company_specific');
    SELECT RAISE(ABORT, 'potential or stronger status requires all company-specific evidence to be currently valid (approved source, not retracted, relationship current)')
    WHERE NEW.evidence_status IN ('potential','strongly_supported','confirmed') AND EXISTS (
        SELECT 1 FROM invalid_candidate_evidence v WHERE v.candidate_id = NEW.candidate_id);
    -- strongly supported: the event itself must be corroborated or primary-confirmed
    SELECT RAISE(ABORT, 'strongly supported requires a corroborated or primary-confirmed event')
    WHERE NEW.evidence_status IN ('strongly_supported','confirmed') AND NOT EXISTS (
        SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
          AND e.verification_state IN ('corroborated','primary_confirmed'));
    -- confirmed: only from strongly supported, through a real acceptance review
    SELECT RAISE(ABORT, 'confirmed requires a prior strongly supported status')
    WHERE NEW.evidence_status = 'confirmed' AND OLD.evidence_status <> 'strongly_supported';
    SELECT RAISE(ABORT, 'accepted status requires a matching acceptance review')
    WHERE NEW.review_status = 'accepted' AND NOT EXISTS (
        SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id
          AND r.candidate_id = NEW.candidate_id AND r.decision = 'accept');
    SELECT RAISE(ABORT, 'rejected review status requires a matching rejection review')
    WHERE NEW.review_status = 'rejected' AND OLD.review_status <> 'rejected' AND NEW.origin = 'rule'
      AND NOT EXISTS (SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id
                      AND r.candidate_id = NEW.candidate_id AND r.decision = 'reject');
    SELECT RAISE(ABORT, 'last_review_id must refer to a review of this candidate')
    WHERE NEW.last_review_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id AND r.candidate_id = NEW.candidate_id);
END;

CREATE TRIGGER trg_exposure_reviews_no_delete BEFORE DELETE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;

CREATE TRIGGER trg_exposure_reviews_no_update BEFORE UPDATE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;

CREATE TRIGGER trg_exposure_reviews_validate BEFORE INSERT ON exposure_reviews
BEGIN
    SELECT RAISE(ABORT, 'review must record the candidate''s current evidence status')
    WHERE NOT EXISTS (SELECT 1 FROM exposure_candidates c WHERE c.candidate_id = NEW.candidate_id
                      AND c.evidence_status = NEW.evidence_status_at_decision);
    SELECT RAISE(ABORT, 'only a strongly supported candidate can be accepted')
    WHERE NEW.decision = 'accept' AND NEW.evidence_status_at_decision <> 'strongly_supported';
    SELECT RAISE(ABORT, 'evidence can only be revoked when a linked company-specific record is invalid')
    WHERE NEW.decision = 'evidence_revoked' AND NOT EXISTS (
        SELECT 1 FROM invalid_candidate_evidence v WHERE v.candidate_id = NEW.candidate_id);
END;

CREATE TRIGGER trg_impact_assessment_inputs_no_replace BEFORE INSERT ON impact_assessment_inputs
WHEN EXISTS (SELECT 1 FROM impact_assessment_inputs t WHERE t.input_id = NEW.input_id)
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_impact_inputs_no_delete BEFORE DELETE ON impact_assessment_inputs
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs are append-only'); END;

CREATE TRIGGER trg_impact_inputs_no_update BEFORE UPDATE ON impact_assessment_inputs
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs are append-only'); END;

CREATE TRIGGER trg_impact_inputs_validate BEFORE INSERT ON impact_assessment_inputs
BEGIN
    SELECT RAISE(ABORT, 'exposure candidate must belong to the assessment''s event and company')
    WHERE NEW.exposure_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM exposure_candidates x JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE x.candidate_id = NEW.exposure_candidate_id AND x.event_id = a.event_id
          AND x.company_id = a.company_id);
    SELECT RAISE(ABORT, 'event evidence must belong to the assessment''s event and source item')
    WHERE NEW.event_evidence_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM event_evidence e JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE e.evidence_id = NEW.event_evidence_id AND e.event_id = a.event_id
          AND e.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'financial metric must belong to the assessment''s company and source item')
    WHERE NEW.financial_metric_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM financial_metrics m JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE m.metric_id = NEW.financial_metric_id AND m.company_id = a.company_id
          AND m.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'commodity price must match its source item')
    WHERE NEW.commodity_price_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM commodity_prices c WHERE c.price_id = NEW.commodity_price_id
          AND c.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'synthetic input can only support a synthetic assessment')
    WHERE EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.is_synthetic = 0)
      AND (EXISTS (SELECT 1 FROM source_items i JOIN sources s USING(source_id)
                   WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1)
        OR EXISTS (SELECT 1 FROM exposure_candidates x WHERE x.candidate_id = NEW.exposure_candidate_id
                   AND x.is_synthetic = 1));
    SELECT RAISE(ABORT, 'an exposure input attached to a provisional assessment must be strongly supported or confirmed')
    WHERE NEW.exposure_candidate_id IS NOT NULL
      AND EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.assessment_status = 'provisional')
      AND NOT EXISTS (SELECT 1 FROM exposure_candidates_current c WHERE c.candidate_id = NEW.exposure_candidate_id
                      AND c.effective_status IN ('strongly_supported','confirmed'));
    SELECT RAISE(ABORT, 'inputs cannot be added to a terminal assessment')
    WHERE EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.assessment_status IN ('confirmed_conclusion','withdrawn_evidence_invalid',
                                              'rejected_by_review'));
END;

CREATE TRIGGER trg_impact_assessment_revisions_no_replace BEFORE INSERT ON impact_assessment_revisions
WHEN EXISTS (SELECT 1 FROM impact_assessment_revisions t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_impact_revisions_no_delete BEFORE DELETE ON impact_assessment_revisions
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions are append-only'); END;

CREATE TRIGGER trg_impact_revisions_no_update BEFORE UPDATE ON impact_assessment_revisions
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions are append-only'); END;

CREATE TRIGGER trg_impact_revisions_only_current BEFORE INSERT ON impact_assessment_revisions
WHEN NOT EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                 AND a.current_revision = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'revisions are written by triggers for the current revision only'); END;

CREATE TRIGGER trg_impact_assessments_insert BEFORE INSERT ON impact_assessments
BEGIN
    SELECT RAISE(ABORT, 'assessments start at revision 1') WHERE NEW.current_revision <> 1;
    SELECT RAISE(ABORT, 'assessments are created as scenario_only or needs_review; upgrade after linking inputs')
    WHERE NEW.assessment_status NOT IN ('scenario_only','needs_review');
    SELECT RAISE(ABORT, 'a new assessment cannot carry a review') WHERE NEW.last_review_id IS NOT NULL;
    SELECT RAISE(ABORT, 'a refuted event cannot have a current assessment')
    WHERE NEW.scenario_kind = 'current' AND EXISTS (
        SELECT 1 FROM events e WHERE e.event_id = NEW.event_id AND e.verification_state = 'refuted');
    SELECT RAISE(ABORT, 'fictional (cmp-syn-*) companies require a synthetic assessment')
    WHERE NEW.is_synthetic = 0 AND NEW.company_id GLOB 'cmp-syn-*';
    SELECT RAISE(ABORT, 'expiry policy must be approved and in effect, with no overlapping approvals')
    WHERE NEW.expiry_policy_version IS NOT NULL AND (
        NOT EXISTS (SELECT 1 FROM impact_expiry_policies_current p
                    WHERE p.policy_version = NEW.expiry_policy_version AND p.status <> 'draft'
                      AND p.effective_from_utc <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                      AND (p.effective_to_utc IS NULL
                           OR strftime('%Y-%m-%dT%H:%M:%SZ', 'now') < p.effective_to_utc))
        OR EXISTS (SELECT 1 FROM impact_expiry_policy_overlaps));
END;

CREATE TRIGGER trg_impact_assessments_no_delete BEFORE DELETE ON impact_assessments
BEGIN SELECT RAISE(ABORT, 'impact assessments cannot be deleted'); END;

CREATE TRIGGER trg_impact_assessments_no_replace BEFORE INSERT ON impact_assessments
WHEN EXISTS (SELECT 1 FROM impact_assessments t WHERE t.assessment_id = NEW.assessment_id OR (t.event_id = NEW.event_id AND t.company_id = NEW.company_id AND t.mechanism_id = NEW.mechanism_id AND t.scenario_kind = NEW.scenario_kind AND t.transmission_version = NEW.transmission_version))
BEGIN SELECT RAISE(ABORT, 'impact_assessments: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_impact_assessments_rev1 AFTER INSERT ON impact_assessments
BEGIN
    INSERT INTO impact_assessment_revisions VALUES (
        NEW.assessment_id, 1, NEW.created_at_utc, NULL, NEW.assessment_status, NEW.status_reason,
        NEW.actor_type, NEW.changed_by, NULL,
        json_object('assessment_status', NEW.assessment_status, 'status_reason', NEW.status_reason,
                    'direction', NEW.direction, 'magnitude_level', NEW.magnitude_level,
                    'magnitude_basis', NEW.magnitude_basis, 'horizon', NEW.horizon,
                    'evidence_confidence', NEW.evidence_confidence, 'exposure_confidence', NEW.exposure_confidence,
                    'direction_confidence', NEW.direction_confidence,
                    'magnitude_confidence', NEW.magnitude_confidence,
                    'scenario_uncertainty', NEW.scenario_uncertainty, 'event_revision_no', NEW.event_revision_no,
                    'expiry_policy_version', NEW.expiry_policy_version, 'freshness_basis', NEW.freshness_basis,
                    'is_synthetic', NEW.is_synthetic),
        '[]');
END;

CREATE TRIGGER trg_impact_assessments_revision AFTER UPDATE ON impact_assessments
BEGIN
    INSERT INTO impact_assessment_revisions VALUES (
        NEW.assessment_id, NEW.current_revision, NEW.updated_at_utc, OLD.assessment_status,
        NEW.assessment_status, NEW.status_reason, NEW.actor_type, NEW.changed_by,
        CASE WHEN NEW.last_review_id IS NOT OLD.last_review_id THEN NEW.last_review_id END,
        json_object('assessment_status', NEW.assessment_status, 'status_reason', NEW.status_reason,
                    'direction', NEW.direction, 'magnitude_level', NEW.magnitude_level,
                    'magnitude_basis', NEW.magnitude_basis, 'horizon', NEW.horizon,
                    'evidence_confidence', NEW.evidence_confidence, 'exposure_confidence', NEW.exposure_confidence,
                    'direction_confidence', NEW.direction_confidence,
                    'magnitude_confidence', NEW.magnitude_confidence,
                    'scenario_uncertainty', NEW.scenario_uncertainty, 'event_revision_no', NEW.event_revision_no,
                    'expiry_policy_version', NEW.expiry_policy_version, 'freshness_basis', NEW.freshness_basis,
                    'is_synthetic', NEW.is_synthetic),
        COALESCE((SELECT json_group_array(json_object('input_id', i.input_id, 'kind', i.input_kind,
                    'valid', CASE WHEN v.input_id IS NULL THEN 1 ELSE 0 END, 'invalid_reason', v.invalid_reason))
                  FROM impact_assessment_inputs i LEFT JOIN impact_invalid_inputs v ON v.input_id = i.input_id
                  WHERE i.assessment_id = NEW.assessment_id), '[]'));
END;

CREATE TRIGGER trg_impact_assessments_update BEFORE UPDATE ON impact_assessments
BEGIN
    SELECT RAISE(ABORT, 'each update must move to the next revision')
    WHERE NEW.current_revision <> OLD.current_revision + 1;
    SELECT RAISE(ABORT, 'assessment identity cannot change')
    WHERE NEW.event_id <> OLD.event_id OR NEW.company_id <> OLD.company_id
       OR NEW.mechanism_id <> OLD.mechanism_id OR NEW.scenario_kind <> OLD.scenario_kind
       OR NEW.transmission_version <> OLD.transmission_version OR NEW.is_synthetic <> OLD.is_synthetic
       OR NEW.created_at_utc <> OLD.created_at_utc;
    SELECT RAISE(ABORT, 'expiry_policy_version and freshness_basis are fixed at creation')
    WHERE NEW.expiry_policy_version IS NOT OLD.expiry_policy_version
       OR NEW.freshness_basis <> OLD.freshness_basis;
    -- strict transition matrix for terminal and confirmed states
    SELECT RAISE(ABORT, 'a terminal assessment can only be reinstated to provisional after a human accept review')
    WHERE OLD.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review')
      AND NOT (NEW.assessment_status = 'provisional' AND NEW.status_reason = 'reinstated'
               AND NEW.actor_type = 'human');
    SELECT RAISE(ABORT, 'a confirmed conclusion can only be revalidated or withdrawn by the system, or rejected by review')
    WHERE OLD.assessment_status = 'confirmed_conclusion'
      AND NOT ((NEW.assessment_status IN ('needs_revalidation','withdrawn_evidence_invalid')
                AND NEW.actor_type = 'system' AND NEW.last_review_id IS OLD.last_review_id)
               OR (NEW.assessment_status = 'rejected_by_review' AND NEW.actor_type = 'human'));
    -- human reasons need a matching review of this assessment, written for this transition
    SELECT RAISE(ABORT, 'human decision requires a matching new review of this assessment')
    WHERE NEW.status_reason IN ('reviewer_accepted','reviewer_rejected','reviewer_needs_more_evidence',
                                'reviewer_requested_revalidation','reinstated')
      AND (NEW.last_review_id IS OLD.last_review_id OR NOT EXISTS (
            SELECT 1 FROM impact_reviews r WHERE r.review_id = NEW.last_review_id
              AND r.assessment_id = NEW.assessment_id AND r.status_at_decision = OLD.assessment_status
              AND r.decision = CASE NEW.status_reason
                    WHEN 'reviewer_accepted' THEN 'accept' WHEN 'reinstated' THEN 'accept'
                    WHEN 'reviewer_rejected' THEN 'reject'
                    WHEN 'reviewer_needs_more_evidence' THEN 'needs_more_evidence'
                    ELSE 'request_revalidation' END));
    SELECT RAISE(ABORT, 'confirmation requires a prior provisional status')
    WHERE NEW.assessment_status = 'confirmed_conclusion' AND OLD.assessment_status <> 'provisional';
    -- a chain that was ever confirmed returns to provisional only by human reinstatement
    SELECT RAISE(ABORT, 'a previously confirmed or terminal assessment needs human reinstatement')
    WHERE NEW.assessment_status = 'provisional' AND NEW.status_reason <> 'reinstated'
      AND (OLD.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review')
           OR EXISTS (SELECT 1 FROM impact_assessment_revisions h WHERE h.assessment_id = OLD.assessment_id
                      AND h.new_status = 'confirmed_conclusion'));
    SELECT RAISE(ABORT, 'reinstatement leads to provisional only')
    WHERE NEW.status_reason = 'reinstated' AND NEW.assessment_status <> 'provisional';
    -- write-time evidence checks for provisional / confirmed
    SELECT RAISE(ABORT, 'provisional or confirmed requires valid inputs')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND EXISTS (
        SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = NEW.assessment_id);
    SELECT RAISE(ABORT, 'provisional or confirmed requires an eligible exposure input')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NOT EXISTS (
        SELECT 1 FROM impact_assessment_inputs i JOIN exposure_candidates_current c
          ON c.candidate_id = i.exposure_candidate_id
        WHERE i.assessment_id = NEW.assessment_id
          AND c.effective_status IN ('strongly_supported','confirmed'));
    SELECT RAISE(ABORT, 'every exposure input of a provisional assessment must be strongly supported or confirmed')
    WHERE NEW.assessment_status = 'provisional' AND EXISTS (
        SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
          ON c.candidate_id = i.exposure_candidate_id
        WHERE i.assessment_id = NEW.assessment_id AND i.exposure_candidate_id IS NOT NULL
          AND (c.effective_status IS NULL OR c.effective_status NOT IN ('strongly_supported','confirmed')));
    SELECT RAISE(ABORT, 'a confirmed conclusion requires confirmed exposures and a corroborated event')
    WHERE NEW.assessment_status = 'confirmed_conclusion' AND (
        EXISTS (SELECT 1 FROM impact_assessment_inputs i JOIN exposure_candidates_current c
                  ON c.candidate_id = i.exposure_candidate_id
                WHERE i.assessment_id = NEW.assessment_id AND c.effective_status <> 'confirmed')
        OR NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
                       AND e.verification_state IN ('corroborated','primary_confirmed')));
    SELECT RAISE(ABORT, 'refuted, rumour or disputed events cannot support provisional or confirmed current assessments')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NEW.scenario_kind = 'current'
      AND EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
                  AND (e.verification_state = 'refuted' OR e.status_stage = 'rumour'
                       OR (e.verification_state = 'disputed' AND NEW.assessment_status = 'confirmed_conclusion')));
    SELECT RAISE(ABORT, 'a disputed event allows only mixed or unknown direction')
    WHERE NEW.assessment_status = 'provisional' AND NEW.direction NOT IN ('mixed','unknown')
      AND EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id AND e.verification_state = 'disputed');
    SELECT RAISE(ABORT, 'freshness not established: at most needs_review')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'not_established';
    -- policy-based freshness cannot be evaluated by the database yet (rules are not machine-checked), so it
    -- never unlocks provisional/confirmed; explicit expiry must be verifiable from a linked exposure record
    SELECT RAISE(ABORT, 'policy-based freshness is not yet database-verifiable: at most needs_review')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'policy_expiry';
    SELECT RAISE(ABORT, 'explicit source expiry not verified: every linked exposure record needs a real, unexpired valid_to')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'explicit_source_expiry'
      AND NOT EXISTS (SELECT 1 FROM impact_explicit_freshness f WHERE f.assessment_id = NEW.assessment_id);
    SELECT RAISE(ABORT, 'an unknown transmission step requires unknown direction')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NEW.direction <> 'unknown'
      AND EXISTS (SELECT 1 FROM impact_transmission_steps t WHERE t.assessment_id = NEW.assessment_id
                  AND t.revision_no = OLD.current_revision AND t.sign IS NULL);
    SELECT RAISE(ABORT, 'evidence_expired requires an explicit source expiry or an approved policy')
    WHERE NEW.status_reason = 'evidence_expired' AND NEW.freshness_basis = 'not_established';
    -- review binding (replay protection) and direction-change authorisation
    SELECT RAISE(ABORT, 'a linked review cannot be removed')
    WHERE OLD.last_review_id IS NOT NULL AND NEW.last_review_id IS NULL;
    SELECT RAISE(ABORT, 'a review can only be linked by a human decision')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id
      AND NOT (NEW.actor_type = 'human' AND NEW.status_reason IN ('reviewer_accepted','reviewer_rejected',
               'reviewer_needs_more_evidence','reviewer_requested_revalidation','reinstated'));
    SELECT RAISE(ABORT, 'review already used: each review authorises exactly one transition')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id AND EXISTS (
        SELECT 1 FROM impact_assessment_revisions h WHERE h.review_id = NEW.last_review_id);
    SELECT RAISE(ABORT, 'stale review: only the assessment''s newest review can authorise a transition')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id AND NEW.last_review_id IS NOT (
        SELECT MAX(r.review_id) FROM impact_reviews r WHERE r.assessment_id = NEW.assessment_id);
    -- Substantive fields change only with a new human review. Without one, a single field may move one way:
    -- towards caution (direction/horizon -> unknown, magnitude -> not_assessable, a confidence downwards,
    -- scenario uncertainty wider). Other fields, magnitude_basis and affected lines, never change unreviewed.
    SELECT RAISE(ABORT, 'substantive change requires a new human review (only single moves towards caution are exempt)')
    WHERE NOT (NEW.actor_type = 'human' AND NEW.last_review_id IS NOT OLD.last_review_id) AND (
           (NEW.direction IS NOT OLD.direction AND NEW.direction <> 'unknown')
        OR (NEW.horizon IS NOT OLD.horizon AND NEW.horizon <> 'unknown')
        OR (NEW.magnitude_level IS NOT OLD.magnitude_level AND NEW.magnitude_level <> 'not_assessable')
        OR NEW.magnitude_basis IS NOT OLD.magnitude_basis
        OR NEW.affected_lines_json IS NOT OLD.affected_lines_json
        OR (CASE NEW.evidence_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.evidence_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.exposure_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.exposure_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.direction_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.direction_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.magnitude_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.magnitude_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.scenario_uncertainty WHEN 'narrow' THEN 1 WHEN 'wide' THEN 2 ELSE 3 END)
         < (CASE OLD.scenario_uncertainty WHEN 'narrow' THEN 1 WHEN 'wide' THEN 2 ELSE 3 END));
    SELECT RAISE(ABORT, 'without a new human review only one substantive field may change per update')
    WHERE NOT (NEW.actor_type = 'human' AND NEW.last_review_id IS NOT OLD.last_review_id)
      AND (NEW.direction IS NOT OLD.direction) + (NEW.horizon IS NOT OLD.horizon)
        + (NEW.magnitude_level IS NOT OLD.magnitude_level)
        + (NEW.evidence_confidence IS NOT OLD.evidence_confidence)
        + (NEW.exposure_confidence IS NOT OLD.exposure_confidence)
        + (NEW.direction_confidence IS NOT OLD.direction_confidence)
        + (NEW.magnitude_confidence IS NOT OLD.magnitude_confidence)
        + (NEW.scenario_uncertainty IS NOT OLD.scenario_uncertainty) > 1;
END;

CREATE TRIGGER trg_impact_expiry_policy_events_no_replace BEFORE INSERT ON impact_expiry_policy_events
WHEN EXISTS (SELECT 1 FROM impact_expiry_policy_events t WHERE t.policy_event_id = NEW.policy_event_id OR (t.policy_version = NEW.policy_version AND t.event_type = NEW.event_type))
BEGIN SELECT RAISE(ABORT, 'impact_expiry_policy_events: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_policy_events_no_delete BEFORE DELETE ON impact_expiry_policy_events
BEGIN SELECT RAISE(ABORT, 'policy lifecycle events are immutable'); END;

CREATE TRIGGER trg_policy_events_no_update BEFORE UPDATE ON impact_expiry_policy_events
BEGIN SELECT RAISE(ABORT, 'policy lifecycle events are immutable'); END;

CREATE TRIGGER trg_policy_events_validate BEFORE INSERT ON impact_expiry_policy_events
BEGIN
    SELECT RAISE(ABORT, 'a version can only be retired after it is approved')
    WHERE NEW.event_type = 'retired' AND NOT EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.policy_version = NEW.policy_version AND a.event_type = 'approved');
    SELECT RAISE(ABORT, 'retirement cannot precede the effective start')
    WHERE NEW.event_type = 'retired' AND EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.policy_version = NEW.policy_version AND a.event_type = 'approved'
          AND NEW.effective_to_utc < a.effective_from_utc);
    SELECT RAISE(ABORT, 'overlapping expiry-policy approval')
    WHERE NEW.event_type = 'approved' AND EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.event_type = 'approved' AND a.policy_version <> NEW.policy_version
          AND NOT EXISTS (SELECT 1 FROM impact_expiry_policy_events r
                          WHERE r.policy_version = a.policy_version AND r.event_type = 'retired'
                            AND r.effective_to_utc <= NEW.effective_from_utc));
END;

CREATE TRIGGER trg_impact_expiry_policy_versions_no_replace BEFORE INSERT ON impact_expiry_policy_versions
WHEN EXISTS (SELECT 1 FROM impact_expiry_policy_versions t WHERE t.policy_version = NEW.policy_version)
BEGIN SELECT RAISE(ABORT, 'impact_expiry_policy_versions: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_policy_versions_no_delete BEFORE DELETE ON impact_expiry_policy_versions
BEGIN SELECT RAISE(ABORT, 'policy versions are immutable'); END;

CREATE TRIGGER trg_policy_versions_no_update BEFORE UPDATE ON impact_expiry_policy_versions
BEGIN SELECT RAISE(ABORT, 'policy versions are immutable; draft a new version'); END;

CREATE TRIGGER trg_impact_reviews_no_delete BEFORE DELETE ON impact_reviews
BEGIN SELECT RAISE(ABORT, 'impact_reviews are append-only'); END;

CREATE TRIGGER trg_impact_reviews_no_replace BEFORE INSERT ON impact_reviews
WHEN EXISTS (SELECT 1 FROM impact_reviews t WHERE t.review_id = NEW.review_id)
BEGIN SELECT RAISE(ABORT, 'impact_reviews: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_impact_reviews_no_update BEFORE UPDATE ON impact_reviews
BEGIN SELECT RAISE(ABORT, 'impact_reviews are append-only'); END;

CREATE TRIGGER trg_impact_reviews_validate BEFORE INSERT ON impact_reviews
BEGIN
    SELECT RAISE(ABORT, 'review must record the assessment''s current status')
    WHERE NOT EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                      AND a.assessment_status = NEW.status_at_decision);
    SELECT RAISE(ABORT, 'accept is only allowed for provisional assessments or reinstatement')
    WHERE NEW.decision = 'accept' AND NEW.status_at_decision NOT IN
          ('provisional','withdrawn_evidence_invalid','rejected_by_review','needs_revalidation');
    SELECT RAISE(ABORT, 'cannot accept a provisional assessment with invalid inputs')
    WHERE NEW.decision = 'accept' AND NEW.status_at_decision = 'provisional'
      AND EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = NEW.assessment_id);
END;

CREATE TRIGGER trg_impact_scenarios_no_delete BEFORE DELETE ON impact_scenarios
BEGIN SELECT RAISE(ABORT, 'impact_scenarios are append-only'); END;

CREATE TRIGGER trg_impact_scenarios_no_replace BEFORE INSERT ON impact_scenarios
WHEN EXISTS (SELECT 1 FROM impact_scenarios t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no AND t.scenario_case = NEW.scenario_case)
BEGIN SELECT RAISE(ABORT, 'impact_scenarios: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_impact_scenarios_no_update BEFORE UPDATE ON impact_scenarios
BEGIN SELECT RAISE(ABORT, 'impact_scenarios are append-only'); END;

CREATE TRIGGER trg_impact_steps_no_delete BEFORE DELETE ON impact_transmission_steps
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps are append-only'); END;

CREATE TRIGGER trg_impact_steps_no_update BEFORE UPDATE ON impact_transmission_steps
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps are append-only'); END;

CREATE TRIGGER trg_impact_transmission_steps_no_replace BEFORE INSERT ON impact_transmission_steps
WHEN EXISTS (SELECT 1 FROM impact_transmission_steps t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no AND t.step_no = NEW.step_no)
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps: duplicate key; existing rows cannot be replaced'); END;

CREATE TRIGGER trg_llm_calls_no_delete BEFORE DELETE ON llm_calls
BEGIN SELECT RAISE(ABORT, 'llm_calls are append-only'); END;

CREATE TRIGGER trg_llm_calls_no_update BEFORE UPDATE ON llm_calls
BEGIN SELECT RAISE(ABORT, 'llm_calls are append-only'); END;

CREATE TRIGGER trg_market_bar_corrections_no_delete BEFORE DELETE ON market_bar_corrections
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections are append-only'); END;

CREATE TRIGGER trg_market_bar_corrections_no_replace BEFORE INSERT ON market_bar_corrections
WHEN EXISTS (SELECT 1 FROM market_bar_corrections c WHERE c.correction_id = NEW.correction_id)
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections: duplicate key; existing corrections cannot be replaced'); END;

CREATE TRIGGER trg_market_bar_corrections_no_update BEFORE UPDATE ON market_bar_corrections
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections are append-only'); END;

CREATE TRIGGER trg_market_bars_no_delete BEFORE DELETE ON market_bars
BEGIN SELECT RAISE(ABORT, 'market_bars are append-only'); END;

CREATE TRIGGER trg_market_bars_no_replace BEFORE INSERT ON market_bars
WHEN EXISTS (SELECT 1 FROM market_bars b WHERE b.source_id = NEW.source_id AND b.symbol = NEW.symbol
             AND b.timeframe = NEW.timeframe AND b.bar_start_utc = NEW.bar_start_utc)
BEGIN SELECT RAISE(ABORT, 'market_bars: duplicate key; existing bars cannot be replaced'); END;

CREATE TRIGGER trg_market_bars_no_update BEFORE UPDATE ON market_bars
BEGIN SELECT RAISE(ABORT, 'market_bars are append-only; record a correction instead'); END;

CREATE TRIGGER trg_source_item_versions_no_delete BEFORE DELETE ON source_item_versions
BEGIN SELECT RAISE(ABORT, 'source_item_versions are append-only'); END;

CREATE TRIGGER trg_source_item_versions_no_update BEFORE UPDATE ON source_item_versions
BEGIN SELECT RAISE(ABORT, 'source_item_versions are append-only'); END;

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

CREATE TRIGGER trg_sources_active_requires_approval BEFORE UPDATE OF lifecycle_status ON sources
WHEN NEW.lifecycle_status = 'ACTIVE'
 AND (NEW.terms_status <> 'approved' OR NEW.access_status <> 'verified_permitted' OR NEW.enabled <> 1)
BEGIN SELECT RAISE(ABORT, 'ACTIVE requires approved terms, verified access and enabled = 1'); END;

CREATE TRIGGER trg_sources_insert_active_requires_approval BEFORE INSERT ON sources
WHEN NEW.lifecycle_status = 'ACTIVE'
 AND (NEW.terms_status <> 'approved' OR NEW.access_status <> 'verified_permitted' OR NEW.enabled <> 1)
BEGIN SELECT RAISE(ABORT, 'ACTIVE requires approved terms, verified access and enabled = 1'); END;
