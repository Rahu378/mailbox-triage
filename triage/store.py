"""Persist triage results. Same tables n8n writes to (sql/schema.sql), so the
Power BI views work no matter which side processed the email.

SQLite by default, Postgres via TRIAGE_DB_URL.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from .config import DB_URL, ROOT


class Store:
    def __init__(self, url: str = DB_URL):
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url)
        self.pg = self.engine.dialect.name == "postgresql"
        ddl = (ROOT / "sql" / "schema.sql").read_text()
        if not self.pg:
            ddl = ddl.replace("JSONB", "TEXT").replace("TIMESTAMPTZ", "TEXT").replace("BIGSERIAL", "INTEGER")
            ddl = ddl.replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
        with self.engine.begin() as conn:
            for stmt in ddl.split(";\n"):
                body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()
                if body:
                    conn.exec_driver_sql(body)
            if self.pg:
                conn.exec_driver_sql((ROOT / "sql" / "views.sql").read_text())

    def save(self, email: dict, r: dict) -> None:
        ex, d = r["extraction"], r["decision"]
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        j = json.dumps
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO emails (email_id, received_at, from_name, from_addr, subject, body)
                                 VALUES (:id, :rec, :fn, :fa, :s, :b) ON CONFLICT (email_id) DO NOTHING"""),
                         dict(id=email["email_id"], rec=email["received_at"], fn=email["from_name"],
                              fa=email["from_addr"], s=email["subject"], b=email["body"]))
            conn.execute(text("""INSERT INTO triage_results (email_id, processed_at, extractor, category, confidence,
                                   trade_ids, cusip, isin, quantity, settlement_date, deadline, counterparty, route,
                                   priority, sla_gap_bdays, reasons, validation_errors, ssi_flags, jira_key, latency_ms)
                                 VALUES (:id, :now, :x, :c, :conf, :t, :cu, :is, :q, :sd, :dl, :cp, :r, :p, :g, :rs,
                                   :ve, :sf, :jk, :lat)
                                 ON CONFLICT (email_id) DO NOTHING"""),
                         dict(id=r["email_id"], now=now, x=ex["extractor"], c=ex["category"], conf=ex["confidence"],
                              t=j(ex["trade_ids"]), cu=ex["cusip"], **{"is": ex["isin"]}, q=ex["quantity"],
                              sd=ex["settlement_date"], dl=ex["deadline"], cp=ex["counterparty"], r=d["route"],
                              p=d["priority"], g=d["sla_gap_bdays"], rs=j(d["reasons"]), ve=j(d["validation_errors"]),
                              sf=j(d["ssi_flags"]), jk=r["jira_key"], lat=r["latency_ms"]))
            if d["route"] == "SSI_CALLBACK":
                conn.execute(text("""INSERT INTO ssi_callbacks (email_id, counterparty, flags, status, created_at)
                                     VALUES (:id, :cp, :f, 'PENDING_CALLBACK', :now) ON CONFLICT (email_id) DO NOTHING"""),
                             dict(id=r["email_id"], cp=ex["counterparty"], f=j(d["ssi_flags"]), now=now))
            elif d["route"] == "HUMAN_REVIEW":
                conn.execute(text("""INSERT INTO review_queue (email_id, reasons, status, created_at)
                                     VALUES (:id, :rs, 'OPEN', :now) ON CONFLICT (email_id) DO NOTHING"""),
                             dict(id=r["email_id"], rs=j(d["reasons"]), now=now))
            if r["jira_key"] and r["jira_action"] == "created":
                conn.execute(text("""INSERT INTO jira_tickets (jira_key, email_id, category, priority, created_at)
                                     VALUES (:k, :id, :c, :p, :now) ON CONFLICT (jira_key) DO NOTHING"""),
                             dict(k=r["jira_key"], id=r["email_id"], c=ex["category"], p=d["priority"], now=now))
            if r["draft"]:
                conn.execute(text("""INSERT INTO reply_drafts (email_id, jira_key, draft, status, created_at)
                                     VALUES (:id, :k, :dr, 'PENDING_APPROVAL', :now) ON CONFLICT (email_id) DO NOTHING"""),
                             dict(id=r["email_id"], k=r["jira_key"], dr=r["draft"], now=now))
            for step, detail in r["steps"]:
                conn.execute(text("INSERT INTO audit_log (email_id, ts, step, detail) VALUES (:id, :now, :s, :d)"),
                             dict(id=r["email_id"], now=now, s=step, d=detail))

    def approve_draft(self, email_id: str, approver: str, new_text: str | None = None) -> None:
        """The only way a draft moves forward. n8n's approval webhook does the same update, then sends."""
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        with self.engine.begin() as conn:
            n = conn.execute(text("""UPDATE reply_drafts SET status = 'APPROVED', approved_by = :a, approved_at = :now,
                                       draft = COALESCE(:t, draft)
                                     WHERE email_id = :id AND status = 'PENDING_APPROVAL'"""),
                             dict(a=approver, now=now, t=new_text, id=email_id)).rowcount
            if n != 1:
                raise ValueError(f"no pending draft for {email_id}")
            conn.execute(text("INSERT INTO audit_log (email_id, ts, step, detail) VALUES (:id, :now, 'approve', :a)"),
                         dict(id=email_id, now=now, a=approver))

    def query(self, sql: str) -> list[dict]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(sql))]
