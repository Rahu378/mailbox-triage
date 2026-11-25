"""email -> extract -> controls -> (Jira ticket | SSI call-back | human review | FYI) -> reply draft -> store.

This is the Python twin of n8n/mailbox_triage.json. n8n runs it in production. This
version exists so the same logic can be tested, benchmarked and replayed on the
GitHub Pages demo.
"""
from __future__ import annotations

import time

from .config import CONFIDENCE_FLOOR
from .controls import decide
from .drafts import draft_reply
from .extract import RuleExtractor
from .jira import JiraClient, build_issue, dedupe_key


class Triage:
    def __init__(self, extractor=None, jira: JiraClient | None = None, store=None, floor: float = CONFIDENCE_FLOOR):
        self.extractor = extractor or RuleExtractor()
        self.jira = jira or JiraClient()
        self.store = store
        self.floor = floor

    def process(self, email: dict) -> dict:
        t0 = time.perf_counter()
        steps = []
        ex = self.extractor.extract(email)
        steps.append(("extract", f"{ex.extractor}: {ex.category} ({ex.confidence:.2f})"))
        decision = decide(email, ex, self.floor)
        steps.append(("controls", f"{decision.route}" + (f", {decision.priority}" if decision.priority else "")))
        jira_key = jira_action = None
        if decision.route == "JIRA":
            key = dedupe_key(ex)
            existing = self.jira.find_open(key) if key else None
            if existing:
                self.jira.comment(existing, [f"Follow-up email {email['email_id']} from {email['from_addr']}: "
                                             f"{email['subject']}"])
                jira_key, jira_action = existing, "commented"
            else:
                jira_key, jira_action = self.jira.create(build_issue(email, ex, decision), key), "created"
            steps.append(("jira", f"{jira_action} {jira_key}"))
        draft = draft_reply(email, ex, decision, jira_key)
        if draft:
            steps.append(("draft", "reply drafted, waiting for approval"))
        result = dict(email_id=email["email_id"], received_at=email["received_at"], extraction=ex.as_dict(),
                      decision=decision.as_dict(), jira_key=jira_key, jira_action=jira_action, draft=draft,
                      steps=steps, latency_ms=round((time.perf_counter() - t0) * 1000, 2))
        if self.store:
            self.store.save(email, result)
        return result
