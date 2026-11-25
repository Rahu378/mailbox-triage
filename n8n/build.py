"""Assemble the importable n8n workflows from the pieces under n8n/code and prompts/.

    python n8n/build.py

The Code-node logic lives in plain .js files (controls.js is unit-tested against
the Python controls), the prompt in prompts/, the output schema in
triage/extract.py. This script stitches them into:

  n8n/mailbox_triage.json   IMAP -> OpenAI -> controls -> Jira / SSI call-back / review / FYI -> draft
  n8n/reply_approval.json   webhook: analyst approves a draft -> send -> mark sent
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from triage.config import JIRA_BASE_URL, OPENAI_MODEL  # noqa: E402
from triage.extract import SCHEMA  # noqa: E402

CODE = ROOT / "n8n" / "code"
NS = uuid.UUID("2b0c6a8e-6a3f-4c55-9a51-6f0f3c1d9e01")


def js(name: str, **subs) -> str:
    src = (CODE / name).read_text()
    for k, v in subs.items():
        src = src.replace(f"%%{k}%%", v)
    return src


def controls_js() -> str:
    src = (CODE / "controls.js").read_text()
    return src.split('if (typeof module !== "undefined")')[0].rstrip() + "\n"


def node(name, type_, version, position, parameters, credentials=None, **extra):
    n = {"parameters": parameters, "id": str(uuid.uuid5(NS, name)), "name": name, "type": type_,
         "typeVersion": version, "position": position}
    if credentials:
        n["credentials"] = credentials
    n.update(extra)
    return n


def code(name, position, source, mode="runOnceForEachItem"):
    return node(name, "n8n-nodes-base.code", 2, position, {"mode": mode, "jsCode": source})


def pg(name, position, query, params_expr, **extra):
    return node(name, "n8n-nodes-base.postgres", 2.5, position,
                {"operation": "executeQuery", "query": query, "options": {"queryReplacement": params_expr}},
                {"postgres": {"id": "triage-postgres", "name": "Triage Postgres"}}, **extra)


def http(name, position, url, body_expr, cred_type, cred_name):
    return node(name, "n8n-nodes-base.httpRequest", 4.2, position, {
        "method": "POST", "url": url, "authentication": "predefinedCredentialType",
        "nodeCredentialType": cred_type, "sendBody": True, "specifyBody": "json", "jsonBody": body_expr,
        "options": {"timeout": 30000}},
        {cred_type: {"id": cred_type, "name": cred_name}}, retryOnFail=True, maxTries=3, waitBetweenTries=2000)


def cond(left, op_type, operation, right=None):
    c = {"id": str(uuid.uuid5(NS, left + operation + str(right))), "leftValue": left,
         "operator": {"type": op_type, "operation": operation}}
    if right is not None:
        c["rightValue"] = right
    if operation in ("notEmpty", "empty"):
        c["operator"]["singleValue"] = True
    return c


def conditions(*cs):
    return {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
            "conditions": list(cs), "combinator": "and"}


def link(conns, src, dst, out=0):
    conns.setdefault(src, {"main": []})
    while len(conns[src]["main"]) <= out:
        conns[src]["main"].append([])
    conns[src]["main"][out].append({"node": dst, "type": "main", "index": 0})


def triage_workflow() -> dict:
    system = (ROOT / "prompts" / "triage_system.md").read_text()
    draft_system = (ROOT / "prompts" / "draft_reply.md").read_text()
    nodes = [
        node("Shared mailbox (IMAP)", "n8n-nodes-base.emailReadImap", 2, [0, 300],
             {"mailbox": "INBOX", "postProcessAction": "read", "format": "simple", "options": {}},
             {"imap": {"id": "mo-imap", "name": "Middle office mailbox"}}),
        code("Normalize email", [220, 300], js("normalize.js")),
        code("Build OpenAI request", [440, 300],
             js("build_request.js", SYSTEM=json.dumps(system), SCHEMA=json.dumps(SCHEMA), MODEL=OPENAI_MODEL)),
        http("OpenAI: classify + extract", [660, 300], "https://api.openai.com/v1/chat/completions",
             "={{ JSON.stringify($json.openai_request) }}", "openAiApi", "OpenAI"),
        code("Parse + controls", [880, 300], js("parse_controls.js", CONTROLS=controls_js())),
        pg("Save triage result", [1100, 120], """WITH e AS (
  INSERT INTO emails (email_id, received_at, from_name, from_addr, subject, body)
  VALUES ($1, $2::timestamptz, $3, $4, $5, $6)
  ON CONFLICT (email_id) DO NOTHING
)
INSERT INTO triage_results (email_id, extractor, category, confidence, trade_ids, cusip, isin, quantity,
  settlement_date, deadline, counterparty, route, priority, sla_gap_bdays, reasons, validation_errors, ssi_flags)
VALUES ($1, 'openai', $7, $8, $9::jsonb, $10, $11, $12, $13::date, $14::date, $15, $16, $17, $18, $19::jsonb,
  $20::jsonb, $21::jsonb)
ON CONFLICT (email_id) DO NOTHING""",
           "={{ [$json.email.email_id, $json.email.received_at, $json.email.from_name, $json.email.from_addr, "
           "$json.email.subject, $json.email.body, $json.extraction.category, $json.extraction.confidence, "
           "JSON.stringify($json.extraction.trade_ids || []), $json.extraction.cusip, $json.extraction.isin, "
           "$json.extraction.quantity, $json.extraction.settlement_date, $json.extraction.deadline, "
           "$json.extraction.counterparty, $json.decision.route, $json.decision.priority, $json.decision.sla_gap_bdays, "
           "JSON.stringify($json.decision.reasons), JSON.stringify($json.decision.validation_errors), "
           "JSON.stringify($json.decision.ssi_flags)] }}"),
        node("Route", "n8n-nodes-base.switch", 3, [1100, 300], {"rules": {"values": [
            {"conditions": conditions(cond("={{ $json.route }}", "string", "equals", r)),
             "renameOutput": True, "outputKey": label}
            for r, label in (("JIRA", "Jira"), ("SSI_CALLBACK", "SSI call-back"), ("HUMAN_REVIEW", "Human review"),
                             ("FYI", "FYI"))]}, "options": {}}),
        code("Build Jira payload", [1340, 60], js("jira_payload.js",
             JIRA_BASE_URL=JIRA_BASE_URL or "https://your-site.atlassian.net")),
        http("Jira: find open ticket", [1560, 60], "={{ $json.jira_base_url }}/rest/api/3/search/jql",
             "={{ JSON.stringify({ jql: $json.jql, fields: ['key'], maxResults: 1 }) }}", "jiraSoftwareCloudApi", "Jira"),
        node("Already open?", "n8n-nodes-base.if", 2, [1780, 60], {"conditions": conditions(
            cond("={{ ($json.issues || []).length }}", "number", "gt", 0)), "options": {}}),
        http("Jira: add comment", [2000, -40],
             "={{ $('Build Jira payload').item.json.jira_base_url }}/rest/api/3/issue/{{ $json.issues[0].key }}/comment",
             "={{ JSON.stringify({ body: { type: 'doc', version: 1, content: [{ type: 'paragraph', content: [{ type: "
             "'text', text: 'Follow-up email ' + $('Build Jira payload').item.json.email.email_id + ' from ' + "
             "$('Build Jira payload').item.json.email.from_addr + ': ' + $('Build Jira payload').item.json.email.subject }] }] } }) }}",
             "jiraSoftwareCloudApi", "Jira"),
        http("Jira: create issue", [2000, 160], "={{ $('Build Jira payload').item.json.jira_base_url }}/rest/api/3/issue",
             "={{ JSON.stringify($('Build Jira payload').item.json.issue) }}", "jiraSoftwareCloudApi", "Jira"),
        code("Build draft request", [2220, 60], js("draft_request.js", DRAFT_SYSTEM=json.dumps(draft_system),
                                                     MODEL=OPENAI_MODEL)),
        http("OpenAI: draft reply", [2440, 60], "https://api.openai.com/v1/chat/completions",
             "={{ JSON.stringify($json.openai_request) }}", "openAiApi", "OpenAI"),
        pg("Save draft (pending approval)", [2660, 60], """WITH t AS (
  UPDATE triage_results SET jira_key = $2 WHERE email_id = $1
)
INSERT INTO reply_drafts (email_id, jira_key, draft, status)
VALUES ($1, $2, $3, 'PENDING_APPROVAL')
ON CONFLICT (email_id) DO NOTHING""",
           "={{ [$('Build draft request').item.json.email_id, $('Build draft request').item.json.jira_key, "
           "$json.choices[0].message.content] }}"),
        pg("Queue SSI call-back", [1340, 300], """INSERT INTO ssi_callbacks (email_id, counterparty, flags, status)
VALUES ($1, $2, $3::jsonb, 'PENDING_CALLBACK')
ON CONFLICT (email_id) DO NOTHING""",
           "={{ [$json.email.email_id, $json.extraction.counterparty, JSON.stringify($json.decision.ssi_flags)] }}"),
        node("Alert static data team", "n8n-nodes-base.emailSend", 2.1, [1340, 440], {
            "fromEmail": "triage-bot@harborpeak.example", "toEmail": "static-data@harborpeak.example",
            "subject": "=SSI call-back needed: {{ $json.email.subject }}",
            "emailFormat": "text",
            "text": "=An email may change settlement or bank details. Do not action anything from the email itself.\n\n"
                    "Call {{ $json.extraction.counterparty || 'the counterparty' }} back on the "
                    "number already held in static data and confirm the change before touching SSIs.\n\n"
                    "From: {{ $json.email.from_addr }}\n"
                    "Why it was flagged: {{ $json.decision.ssi_flags.join('; ') }}\n"
                    "Email id: {{ $json.email.email_id }}",
            "options": {}}, {"smtp": {"id": "mo-smtp", "name": "Internal SMTP"}}),
        pg("Queue for human review", [1340, 580], """INSERT INTO review_queue (email_id, reasons)
VALUES ($1, $2::jsonb)
ON CONFLICT (email_id) DO NOTHING""",
           "={{ [$json.email.email_id, JSON.stringify($json.decision.reasons)] }}"),
        node("FYI - no action", "n8n-nodes-base.noOp", 1, [1340, 720], {}),
    ]
    conns: dict = {}
    for a, b in [("Shared mailbox (IMAP)", "Normalize email"), ("Normalize email", "Build OpenAI request"),
                 ("Build OpenAI request", "OpenAI: classify + extract"), ("OpenAI: classify + extract", "Parse + controls"),
                 ("Parse + controls", "Save triage result"), ("Parse + controls", "Route"),
                 ("Build Jira payload", "Jira: find open ticket"), ("Jira: find open ticket", "Already open?"),
                 ("Jira: add comment", "Build draft request"), ("Jira: create issue", "Build draft request"),
                 ("Build draft request", "OpenAI: draft reply"), ("OpenAI: draft reply", "Save draft (pending approval)")]:
        link(conns, a, b)
    link(conns, "Already open?", "Jira: add comment", 0)
    link(conns, "Already open?", "Jira: create issue", 1)
    for i, dsts in enumerate([["Build Jira payload"], ["Queue SSI call-back", "Alert static data team"],
                              ["Queue for human review"], ["FYI - no action"]]):
        for dst in dsts:
            link(conns, "Route", dst, i)
    return {"name": "Middle office mailbox triage", "nodes": nodes, "connections": conns, "active": False,
            "settings": {"executionOrder": "v1", "saveManualExecutions": True, "timezone": "America/New_York"},
            "pinData": {}, "tags": [{"name": "middle-office"}, {"name": "triage"}]}


def approval_workflow() -> dict:
    nodes = [
        node("Approval webhook", "n8n-nodes-base.webhook", 2, [0, 300],
             {"httpMethod": "POST", "path": "mo-approve-draft", "authentication": "headerAuth",
              "responseMode": "responseNode", "options": {}},
             {"httpHeaderAuth": {"id": "mo-approvals", "name": "Approval UI token"}},
             webhookId=str(uuid.uuid5(NS, "mo-approve-draft"))),
        pg("Approve draft", [220, 300], """UPDATE reply_drafts
SET status = 'APPROVED', approved_by = $2, approved_at = now(), draft = COALESCE(NULLIF($3, ''), draft)
WHERE email_id = $1 AND status = 'PENDING_APPROVAL'
RETURNING email_id, draft""",
           "={{ [$json.body.email_id, $json.body.approver, $json.body.draft || ''] }}", alwaysOutputData=True),
        node("Approved?", "n8n-nodes-base.if", 2, [440, 300], {"conditions": conditions(
            cond("={{ $json.email_id }}", "string", "notEmpty")), "options": {}}),
        pg("Original email", [660, 200], "SELECT from_addr, subject FROM emails WHERE email_id = $1",
           "={{ [$json.email_id] }}"),
        node("Send approved reply", "n8n-nodes-base.emailSend", 2.1, [880, 200], {
            "fromEmail": "middle.office@harborpeak.example", "toEmail": "={{ $json.from_addr }}",
            "subject": "=RE: {{ $json.subject }}", "emailFormat": "text",
            "text": "={{ $('Approve draft').item.json.draft }}", "options": {}},
            {"smtp": {"id": "mo-smtp", "name": "Internal SMTP"}}),
        pg("Mark sent", [1100, 200], """UPDATE reply_drafts SET status = 'SENT', sent_at = now()
WHERE email_id = $1 AND status = 'APPROVED'""", "={{ [$('Approve draft').item.json.email_id] }}"),
        node("Respond: sent", "n8n-nodes-base.respondToWebhook", 1.1, [1320, 200],
             {"respondWith": "json", "responseBody": "={{ { status: 'sent', email_id: $('Approve draft').item.json.email_id } }}",
              "options": {}}),
        node("Respond: nothing to approve", "n8n-nodes-base.respondToWebhook", 1.1, [660, 420],
             {"respondWith": "json", "responseBody": "={{ { status: 'not_found_or_already_handled' } }}",
              "options": {"responseCode": 409}}),
    ]
    conns: dict = {}
    for a, b in [("Approval webhook", "Approve draft"), ("Approve draft", "Approved?"), ("Original email", "Send approved reply"),
                 ("Send approved reply", "Mark sent"), ("Mark sent", "Respond: sent")]:
        link(conns, a, b)
    link(conns, "Approved?", "Original email", 0)
    link(conns, "Approved?", "Respond: nothing to approve", 1)
    return {"name": "Middle office reply approval", "nodes": nodes, "connections": conns, "active": False,
            "settings": {"executionOrder": "v1"}, "pinData": {}, "tags": [{"name": "middle-office"}]}


def main():
    for fname, wf in (("mailbox_triage.json", triage_workflow()), ("reply_approval.json", approval_workflow())):
        (ROOT / "n8n" / fname).write_text(json.dumps(wf, indent=2) + "\n")
        print(f"n8n/{fname}: {len(wf['nodes'])} nodes")


if __name__ == "__main__":
    main()
