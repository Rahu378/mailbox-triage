"""Jira Cloud tickets (REST API v3).

One ticket per (category, trade) while it's open: a second email about the same
fail becomes a comment, not a duplicate ticket. Without credentials the client
runs dry and hands back fake keys, so everything else can be exercised offline.
"""
from __future__ import annotations

import itertools

from .config import JIRA_API_TOKEN, JIRA_BASE_URL, JIRA_EMAIL, JIRA_PROJECT

LABELS = {"TRADE_QUERY": "trade-query", "SETTLEMENT_FAIL": "settlement-fail", "CA_ELECTION": "ca-election",
          "PRICE_CHALLENGE": "price-challenge"}
PREFIX = {"TRADE_QUERY": "Query", "SETTLEMENT_FAIL": "FAIL", "CA_ELECTION": "Election", "PRICE_CHALLENGE": "Price"}


def _adf(paragraphs: list[str]) -> dict:
    """Atlassian Document Format, which v3 needs for descriptions and comments."""
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs if p]}


def dedupe_key(ex) -> str | None:
    ref = ex.trade_ids[0] if ex.trade_ids else (ex.cusip or ex.isin)
    return f"{LABELS[ex.category]}:{ref}" if ref else None


def build_issue(email: dict, ex, decision) -> dict:
    ref = ", ".join(ex.trade_ids) or ex.cusip or ex.isin or "no ref"
    bits = [PREFIX[ex.category], ref]
    if ex.quantity:
        bits.append(f"{ex.quantity:,}")
    if ex.settlement_date:
        bits.append(f"SD {ex.settlement_date}")
    if ex.deadline:
        bits.append(f"deadline {ex.deadline}")
    if ex.counterparty:
        bits.append(ex.counterparty)
    labels = ["mailbox-triage", LABELS[ex.category]] + [f"trade-{t}" for t in ex.trade_ids]
    key_ref = ex.trade_ids[0] if ex.trade_ids else (ex.cusip or ex.isin)
    if key_ref:
        labels.append(f"ref-{key_ref}")
    if decision.priority in ("Highest", "High") and ex.category in ("SETTLEMENT_FAIL", "TRADE_QUERY"):
        labels.append("t1-at-risk")
    fields = {
        "project": {"key": JIRA_PROJECT},
        "issuetype": {"name": "Task"},
        "summary": " | ".join(bits)[:250],
        "priority": {"name": decision.priority},
        "labels": labels,
        "description": _adf([
            f"From {email['from_name']} <{email['from_addr']}> at {email['received_at']}",
            f"Subject: {email['subject']}",
            f"Trade IDs: {ref} | CUSIP: {ex.cusip or '-'} | ISIN: {ex.isin or '-'} | Qty: {ex.quantity or '-'} | "
            f"Settlement: {ex.settlement_date or '-'} | Deadline: {ex.deadline or '-'} | Counterparty: {ex.counterparty or '-'}",
            "Why this priority: " + "; ".join(decision.reasons),
            f"Extractor: {ex.extractor}, confidence {ex.confidence:.2f}. Original email id {email['email_id']}.",
        ]),
    }
    due = ex.settlement_date or ex.deadline
    if due:
        fields["duedate"] = due
    return {"fields": fields}


class JiraClient:
    def __init__(self, base_url=JIRA_BASE_URL, email=JIRA_EMAIL, token=JIRA_API_TOKEN):
        self.base = base_url.rstrip("/")
        self.auth = (email, token)
        self.dry_run = not (base_url and email and token)
        self._seq = itertools.count(2101)
        self._open: dict[str, str] = {}  # dedupe key -> issue key (dry run only)

    def find_open(self, key: str) -> str | None:
        if self.dry_run:
            return self._open.get(key)
        import requests

        category_label, ref = key.split(":", 1)
        jql = (f'project = {JIRA_PROJECT} AND labels = "mailbox-triage" AND labels = "{category_label}" '
               f'AND labels = "ref-{ref}" AND statusCategory != Done')
        r = requests.post(f"{self.base}/rest/api/3/search/jql", auth=self.auth, timeout=20,
                          json={"jql": jql, "fields": ["key"], "maxResults": 1})
        r.raise_for_status()
        issues = r.json().get("issues", [])
        return issues[0]["key"] if issues else None

    def create(self, payload: dict, key: str | None) -> str:
        if self.dry_run:
            issue = f"{payload['fields']['project']['key']}-{next(self._seq)}"
            if key:
                self._open[key] = issue
            return issue
        import requests

        r = requests.post(f"{self.base}/rest/api/3/issue", json=payload, auth=self.auth, timeout=20)
        r.raise_for_status()
        return r.json()["key"]

    def comment(self, issue: str, text: list[str]) -> None:
        if self.dry_run:
            return
        import requests

        r = requests.post(f"{self.base}/rest/api/3/issue/{issue}/comment", json={"body": _adf(text)},
                          auth=self.auth, timeout=20)
        r.raise_for_status()
