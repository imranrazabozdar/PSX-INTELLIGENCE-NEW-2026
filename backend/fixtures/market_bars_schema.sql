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
