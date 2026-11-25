-- Tables shared by the n8n workflow and the Python pipeline. Postgres; triage/store.py adapts it for SQLite.

CREATE TABLE IF NOT EXISTS emails (
    email_id     TEXT PRIMARY KEY,
    received_at  TIMESTAMPTZ NOT NULL,
    from_name    TEXT,
    from_addr    TEXT NOT NULL,
    subject      TEXT,
    body         TEXT
);

CREATE TABLE IF NOT EXISTS triage_results (
    email_id           TEXT PRIMARY KEY REFERENCES emails (email_id),
    processed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    extractor          TEXT NOT NULL,
    category           TEXT NOT NULL,
    confidence         NUMERIC(4, 3),
    trade_ids          JSONB,
    cusip              TEXT,
    isin               TEXT,
    quantity           BIGINT,
    settlement_date    DATE,
    deadline           DATE,
    counterparty       TEXT,
    route              TEXT NOT NULL CHECK (route IN ('JIRA', 'SSI_CALLBACK', 'HUMAN_REVIEW', 'FYI')),
    priority           TEXT,
    sla_gap_bdays      INTEGER,
    reasons            JSONB,
    validation_errors  JSONB,
    ssi_flags          JSONB,
    jira_key           TEXT,
    latency_ms         NUMERIC(10, 2)
);

CREATE TABLE IF NOT EXISTS jira_tickets (
    jira_key     TEXT PRIMARY KEY,
    email_id     TEXT REFERENCES emails (email_id),
    category     TEXT,
    priority     TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SSI changes are never actioned from the email. Someone calls the counterparty on the number already
-- in static data, and only then can the row move on.
CREATE TABLE IF NOT EXISTS ssi_callbacks (
    email_id                TEXT PRIMARY KEY REFERENCES emails (email_id),
    counterparty            TEXT,
    flags                   JSONB,
    status                  TEXT NOT NULL DEFAULT 'PENDING_CALLBACK'
                            CHECK (status IN ('PENDING_CALLBACK', 'VERIFIED', 'REJECTED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_by             TEXT,
    verified_at             TIMESTAMPTZ,
    callback_number_source  TEXT,
    CONSTRAINT callback_needs_a_person CHECK (status = 'PENDING_CALLBACK' OR verified_by IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS review_queue (
    email_id           TEXT PRIMARY KEY REFERENCES emails (email_id),
    reasons            JSONB,
    status             TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by        TEXT,
    resolved_category  TEXT
);

-- Drafts wait for a person. The constraint makes "sent without approval" impossible at the database level.
CREATE TABLE IF NOT EXISTS reply_drafts (
    email_id     TEXT PRIMARY KEY REFERENCES emails (email_id),
    jira_key     TEXT,
    draft        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                 CHECK (status IN ('PENDING_APPROVAL', 'APPROVED', 'DISCARDED', 'SENT')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by  TEXT,
    approved_at  TIMESTAMPTZ,
    sent_at      TIMESTAMPTZ,
    CONSTRAINT sent_needs_approval CHECK (status NOT IN ('APPROVED', 'SENT') OR approved_by IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        BIGSERIAL PRIMARY KEY,
    email_id  TEXT,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    step      TEXT NOT NULL,
    detail    TEXT
);
