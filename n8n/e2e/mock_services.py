"""Local stand-ins for the OpenAI and Jira Cloud APIs, for running the real workflow in a real n8n.

OpenAI: /v1/chat/completions. Calls with a json_schema response_format get the rules extractor's
        answer for the email in the user message. Other calls (the draft) get a short canned reply.
Jira:   /rest/api/3/search/jql, /rest/api/3/issue, /rest/api/3/issue/{key}/comment, with an
        in-memory index so a second email about the same trade finds the open ticket.

    python n8n/e2e/mock_services.py 8899
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from triage.extract import SCHEMA, RuleExtractor  # noqa: E402

EXTRACTOR = RuleExtractor()
SEQ = itertools.count(2101)
OPEN: dict[frozenset, str] = {}
LOG = {"openai_triage": 0, "openai_draft": 0, "jira_search": 0, "jira_create": 0, "jira_comment": 0}


def parse_user(text: str) -> dict:
    head, _, body = text.partition("\n\n")
    m = dict(re.findall(r"^(Received|From|Subject): (.*)$", head, re.M))
    fm = re.match(r"(.*?) <([^>]+)>", m.get("From", ""))
    return dict(email_id="mock", received_at=m["Received"].replace("Z", "").split(".")[0],
                from_name=fm.group(1) if fm else "", from_addr=fm.group(2) if fm else m.get("From", ""),
                subject=m.get("Subject", ""), body=body)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/stats":
            return self.send(LOG)
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if self.path.endswith("/chat/completions"):
            if body.get("response_format", {}).get("type") == "json_schema":
                LOG["openai_triage"] += 1
                ex = EXTRACTOR.extract(parse_user(body["messages"][-1]["content"]))
                out = {k: getattr(ex, k) for k in SCHEMA["required"]}
                return self.send({"choices": [{"message": {"role": "assistant", "content": json.dumps(out)}}]})
            LOG["openai_draft"] += 1
            return self.send({"choices": [{"message": {"role": "assistant",
                                                       "content": "Hi,\n\nThanks, we're on it.\n\nMiddle Office"}}]})
        if self.path.endswith("/rest/api/3/search/jql"):
            LOG["jira_search"] += 1
            labels = frozenset(re.findall(r'labels = "([^"]+)"', body.get("jql", "")))
            key = OPEN.get(labels)
            return self.send({"issues": [{"key": key}] if key else []})
        m = re.search(r"/rest/api/3/issue/([A-Z]+-\d+)/comment$", self.path)
        if m:
            LOG["jira_comment"] += 1
            return self.send({"id": str(next(SEQ))}, 201)
        if self.path.endswith("/rest/api/3/issue"):
            LOG["jira_create"] += 1
            key = f"MO-{next(SEQ)}"
            f = body["fields"]
            assert f["project"]["key"] and f["summary"] and f["priority"]["name"] and f["description"]["type"] == "doc"
            labels = set(f["labels"])
            ref = [x for x in labels if x.startswith("ref-")]
            if ref:
                cat = next(x for x in labels if x in ("trade-query", "settlement-fail", "ca-election", "price-challenge"))
                OPEN[frozenset({"mailbox-triage", cat, ref[0]})] = key
            return self.send({"id": key[3:], "key": key}, 201)
        self.send({"error": f"unexpected {self.path}"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
