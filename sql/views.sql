-- Views the Power BI report reads (Postgres). DirectQuery or import, both work.

CREATE OR REPLACE VIEW vw_triage AS
SELECT r.*, e.from_addr, e.subject, e.received_at,
       (e.received_at AT TIME ZONE 'America/New_York')::date AS received_day,
       EXTRACT(HOUR FROM e.received_at AT TIME ZONE 'America/New_York')::int AS received_hour
FROM triage_results r
JOIN emails e USING (email_id);

CREATE OR REPLACE VIEW vw_daily_volume AS
SELECT received_day, category, route, COUNT(*) AS emails
FROM vw_triage
GROUP BY received_day, category, route;

CREATE OR REPLACE VIEW vw_open_queues AS
SELECT 'SSI call-back' AS queue, COUNT(*) AS open_items, MIN(created_at) AS oldest_item
FROM ssi_callbacks WHERE status = 'PENDING_CALLBACK'
UNION ALL
SELECT 'Human review', COUNT(*), MIN(created_at) FROM review_queue WHERE status = 'OPEN'
UNION ALL
SELECT 'Drafts awaiting approval', COUNT(*), MIN(created_at) FROM reply_drafts WHERE status = 'PENDING_APPROVAL';

CREATE OR REPLACE VIEW vw_t1_at_risk AS
SELECT email_id, category, trade_ids, counterparty, settlement_date, priority, jira_key, received_at
FROM vw_triage
WHERE route = 'JIRA' AND priority IN ('Highest', 'High') AND category IN ('SETTLEMENT_FAIL', 'TRADE_QUERY');

CREATE OR REPLACE VIEW vw_draft_turnaround AS
SELECT d.email_id, d.status, d.created_at, d.approved_at,
       EXTRACT(EPOCH FROM (d.approved_at - d.created_at)) / 60.0 AS minutes_to_approve
FROM reply_drafts d;

CREATE OR REPLACE VIEW vw_counterparty_fails AS
SELECT counterparty, COUNT(*) AS fail_emails,
       COUNT(*) FILTER (WHERE priority = 'Highest') AS due_or_past_due
FROM vw_triage
WHERE category = 'SETTLEMENT_FAIL'
GROUP BY counterparty;
