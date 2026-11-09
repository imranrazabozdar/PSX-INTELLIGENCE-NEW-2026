CREATE TABLE sectors (
    sector_id      TEXT PRIMARY KEY,
    scheme         TEXT NOT NULL CHECK (scheme IN ('PSX')),
    name           TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (scheme, name)
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

CREATE TABLE dataset_loads (
    dataset        TEXT PRIMARY KEY,
    sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
    loaded_at_utc  TEXT NOT NULL,
    record_count   INTEGER NOT NULL CHECK (record_count >= 0)
);

CREATE INDEX ix_companies_status ON companies(listing_status);

CREATE UNIQUE INDEX ux_identifiers_current ON company_identifiers(id_type, value) WHERE valid_to IS NULL;

CREATE INDEX ix_identifiers_company ON company_identifiers(company_id);

CREATE INDEX ix_aliases_normalized ON company_aliases(alias_normalized);

CREATE UNIQUE INDEX ux_classification_current ON company_classifications(company_id) WHERE valid_to IS NULL;
