#!/usr/bin/env bash
# Run the real workflows in a real n8n against Postgres, with OpenAI and Jira replaced by mock_services.py.
#
#   PGURL=postgresql://postgres:postgres@localhost:5432 N8N=npx\ n8n ./n8n/e2e/run_e2e.sh
#
# Needs: n8n 2.x (Node 24), psql, python with this repo's requirements. Edit credentials.example.json
# if your Postgres isn't on localhost:5432 as postgres/postgres.
set -euo pipefail
cd "$(dirname "$0")/../.."
PGURL=${PGURL:-postgresql://postgres:postgres@localhost:5432}
N8N=${N8N:-n8n}
export N8N_USER_FOLDER=${N8N_USER_FOLDER:-$(mktemp -d)}
export N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY:-local-e2e-only}
export N8N_DIAGNOSTICS_ENABLED=false

python -m triage.mailbox >/dev/null
psql "$PGURL/postgres" -qc "DROP DATABASE IF EXISTS triage" -c "CREATE DATABASE triage"
psql "$PGURL/triage" -q -f sql/schema.sql -f sql/views.sql

python n8n/e2e/mock_services.py 8899 & MOCK=$!
trap 'kill $MOCK' EXIT
sleep 1
python n8n/e2e/make_test_workflow.py http://127.0.0.1:8899

$N8N import:credentials --input=n8n/e2e/credentials.example.json
$N8N import:workflow --input=n8n/e2e/out/triage_test.json
$N8N import:workflow --input=n8n/e2e/out/approval_test.json

$N8N execute --id e2eTriage0000001   # first poll: every ticket is new
$N8N execute --id e2eTriage0000001   # same mail again: follow-ups become comments, no duplicate rows
$N8N execute --id e2eApproval00001   # three approvals and one for an email with no draft
curl -s http://127.0.0.1:8899/stats; echo

psql "$PGURL/triage" -c "SELECT route, COUNT(*) FROM triage_results GROUP BY route ORDER BY route" \
                     -c "SELECT status, COUNT(*) FROM reply_drafts GROUP BY status" \
                     -c "SELECT * FROM vw_open_queues"
