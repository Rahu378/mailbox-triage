"""Data + Python bundle for the GitHub Pages demo.

    python -m triage.export_site
"""
from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter, defaultdict

from .benchmark import load, score
from .config import ROOT
from .pipeline import Triage

DOCS = ROOT / "docs"
BROWSER_MODULES = ["__init__.py", "config.py", "calendar.py", "extract.py", "controls.py", "jira.py", "drafts.py",
                   "pipeline.py", "web.py"]


def _dump(name, obj):
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    (DOCS / "data" / name).write_text(json.dumps(obj, separators=(",", ":"), default=str))


def main() -> None:
    emails, labels = load()
    tr = Triage()
    results = [tr.process(e) for e in emails]
    metrics = score(emails, labels, results, "rules")

    rows = []
    for e, r in zip(emails, results):
        lab = labels[e["email_id"]]
        rows.append(dict(email={k: e[k] for k in ("email_id", "received_at", "from_name", "from_addr", "subject", "body",
                                                  "attachments")},
                         label=dict(category=lab["category"], variant=lab["variant"], ssi_change=lab["ssi_change"],
                                    priority=lab["priority"]),
                         result={k: r[k] for k in ("extraction", "decision", "jira_key", "jira_action", "draft", "steps",
                                                   "latency_ms")}))
    _dump("mailbox.json", rows)
    _dump("benchmark.json", metrics)

    by_day = defaultdict(Counter)
    prio = Counter()
    fails = Counter()
    for e, r in zip(emails, results):
        day = e["received_at"][:10]
        by_day[day][r["extraction"]["category"]] += 1
        if r["decision"]["route"] == "JIRA":
            prio[r["decision"]["priority"]] += 1
        if r["extraction"]["category"] == "SETTLEMENT_FAIL" and r["extraction"]["counterparty"]:
            fails[r["extraction"]["counterparty"]] += 1
    lat = sorted(r["latency_ms"] for r in results)
    _dump("dashboard.json", dict(
        by_day={d: dict(c) for d, c in sorted(by_day.items())},
        routes=metrics["routes"], priority=dict(prio), counterparty_fails=fails.most_common(8),
        tickets=sum(1 for r in results if r["jira_action"] == "created"),
        comments=sum(1 for r in results if r["jira_action"] == "commented"),
        drafts=sum(1 for r in results if r["draft"]),
        latency_ms=dict(p50=lat[len(lat) // 2], p95=lat[int(len(lat) * 0.95)]),
    ))
    for f in ("mailbox_triage.json", "reply_approval.json"):
        shutil.copy(ROOT / "n8n" / f, DOCS / "data" / f)
    (DOCS / "py").mkdir(exist_ok=True)
    with zipfile.ZipFile(DOCS / "py" / "triage.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in BROWSER_MODULES:
            z.write(ROOT / "triage" / f, f"triage/{f}")
    size = sum(p.stat().st_size for p in (DOCS / "data").glob("*")) / 1024
    print(f"docs/data {size:.0f} KB · {len(rows)} emails · category {metrics['category_accuracy']:.1%} · "
          f"SSI {metrics['ssi']['routed_to_callback']}/{metrics['ssi']['changes']} · wrong {metrics['outcome'].get('wrong', 0)}")


if __name__ == "__main__":
    main()
