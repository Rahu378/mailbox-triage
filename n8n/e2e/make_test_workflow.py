"""Turn the production workflows into runnable test copies.

Only the edges of the workflow change: the IMAP trigger becomes a manual trigger that replays the synthetic
mailbox, the API base URLs point at mock_services.py, and outbound email becomes a no-op. Every node in
between (Code, HTTP, Switch, IF, Postgres) is the production node, unchanged.

    python n8n/e2e/make_test_workflow.py http://127.0.0.1:8899 [N]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"


def main():
    base = sys.argv[1].rstrip("/")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000
    OUT.mkdir(exist_ok=True)
    emails = [json.loads(x) for x in open(ROOT / "data" / "mailbox.jsonl")][:n]
    imap_items = [{"from": {"text": f"{e['from_name']} <{e['from_addr']}>"}, "subject": e["subject"],
                   "date": e["received_at"] + "Z", "textPlain": e["body"], "messageId": e["email_id"]} for e in emails]

    wf = json.loads((ROOT / "n8n" / "mailbox_triage.json").read_text())
    for node in wf["nodes"]:
        if node["name"] == "Shared mailbox (IMAP)":
            node.update(type="n8n-nodes-base.code", typeVersion=2, credentials={},
                        parameters={"mode": "runOnceForAllItems",
                                    "jsCode": f"return {json.dumps(imap_items)}.map((json) => ({{ json }}));"})
            node.pop("credentials")
        elif node["type"] == "n8n-nodes-base.httpRequest" and "openai.com" in node["parameters"]["url"]:
            node["parameters"]["url"] = node["parameters"]["url"].replace("https://api.openai.com", base)
        elif node["name"] == "Build Jira payload":
            node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace("https://your-site.atlassian.net", base)
        elif node["type"] == "n8n-nodes-base.emailSend":
            node.update(type="n8n-nodes-base.noOp", typeVersion=1, parameters={})
            node.pop("credentials")
    wf["nodes"].append({"parameters": {}, "id": "0b6bb2a9-0000-4000-8000-000000000001", "name": "Start",
                        "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [-220, 300]})
    wf["connections"]["Start"] = {"main": [[{"node": "Shared mailbox (IMAP)", "type": "main", "index": 0}]]}
    wf["name"] = "E2E - mailbox triage"
    wf["id"] = "e2eTriage0000001"
    (OUT / "triage_test.json").write_text(json.dumps(wf, indent=2))

    ap = json.loads((ROOT / "n8n" / "reply_approval.json").read_text())
    for node in ap["nodes"]:
        if node["name"] == "Approval webhook":
            # three real approvals plus one for an email that has no pending draft
            sys.path.insert(0, str(ROOT))
            from triage.pipeline import Triage
            tr = Triage()
            with_drafts = [e["email_id"] for e in emails if tr.process(e)["draft"]][:3]
            reqs = [{"body": {"email_id": eid, "approver": "e2e-analyst"}} for eid in with_drafts]
            reqs.append({"body": {"email_id": "MSG-99999", "approver": "e2e-analyst"}})
            node.update(type="n8n-nodes-base.code", typeVersion=2,
                        parameters={"mode": "runOnceForAllItems", "jsCode": f"return {json.dumps(reqs)}.map((json) => ({{ json }}));"})
            node.pop("credentials")
            node.pop("webhookId", None)
        elif node["type"] in ("n8n-nodes-base.respondToWebhook", "n8n-nodes-base.emailSend"):
            node.update(type="n8n-nodes-base.noOp", typeVersion=1, parameters={})
            node.pop("credentials", None)
    ap["nodes"].append({"parameters": {}, "id": "0b6bb2a9-0000-4000-8000-000000000002", "name": "Start",
                        "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [-220, 300]})
    ap["connections"]["Start"] = {"main": [[{"node": "Approval webhook", "type": "main", "index": 0}]]}
    ap["name"] = "E2E - reply approval"
    ap["id"] = "e2eApproval00001"
    (OUT / "approval_test.json").write_text(json.dumps(ap, indent=2))
    print(f"wrote {OUT}/triage_test.json ({len(emails)} emails) and approval_test.json")


if __name__ == "__main__":
    main()
