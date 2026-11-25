"""Entry point for the browser demo (Pyodide): triage one email with the same pipeline as the CLI."""
from __future__ import annotations

import datetime as dt
import json

from .jira import JiraClient, build_issue
from .pipeline import Triage

_triage = Triage(jira=JiraClient(base_url=""))


def triage(subject: str, body: str, from_name: str, from_addr: str, received_at: str | None = None) -> str:
    email = dict(email_id="TRY-1", received_at=received_at or dt.datetime(2026, 11, 18, 10, 30).isoformat(),
                 from_name=from_name, from_addr=from_addr, to="middle.office@harborpeak.example", subject=subject,
                 body=body)
    r = _triage.process(email)
    if r["decision"]["route"] == "JIRA":
        from .extract import Extraction
        from .controls import Decision

        ex = Extraction(**{k: v for k, v in r["extraction"].items()})
        r["jira_payload"] = build_issue(email, ex, Decision(**r["decision"]))
    return json.dumps(r, default=str)
