"""Score the triage against the mailbox labels.

    python -m triage.benchmark                   # rule extractor (no key needed)
    python -m triage.benchmark --extractor openai

What's measured:
  * category accuracy, overall / per class / by how the email was written
  * field accuracy: trade ID, CUSIP/ISIN, quantity, settlement date, deadline, counterparty
  * SSI control: every email that changes settlement details must land in the call-back queue
  * routing outcome: correct, deferred to a human (safe), or wrong (unsafe)
  * priority accuracy on tickets that were opened under the right category
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict

from .config import DATA_DIR, ROOT
from .extract import CATEGORIES, OpenAIExtractor, RuleExtractor
from .pipeline import Triage

FIELDS = ("trade_ids", "security", "quantity", "settlement_date", "deadline", "counterparty")


def load():
    emails = [json.loads(x) for x in open(DATA_DIR / "mailbox.jsonl")]
    labels = {json.loads(x)["email_id"]: json.loads(x) for x in open(DATA_DIR / "labels.jsonl")}
    return emails, labels


def expected_route(lab):
    if lab["ssi_change"]:
        return "SSI_CALLBACK"
    return "FYI" if lab["category"] == "OTHER" else "JIRA"


def score(emails, labels, results, extractor_name):
    n = len(results)
    conf = defaultdict(Counter)
    by_style = defaultdict(lambda: [0, 0])
    fields = {f: [0, 0] for f in FIELDS}
    outcome = Counter()
    unsafe, ssi_fp = [], []
    prio = [0, 0]
    ssi = [0, 0]
    for e, r in zip(emails, results):
        lab = labels[e["email_id"]]
        ex, d = r["extraction"], r["decision"]
        conf[lab["category"]][ex["category"]] += 1
        style = "loose" if lab["variant"] == "loose" else ("plain" if lab["variant"] == "plain" else "hard")
        by_style[style][0] += 1
        by_style[style][1] += ex["category"] == lab["category"]
        if lab["trade_ids"]:
            fields["trade_ids"][0] += 1
            fields["trade_ids"][1] += ex["trade_ids"] == lab["trade_ids"]
        if lab["cusip"] or lab["isin"]:
            fields["security"][0] += 1
            fields["security"][1] += (lab["cusip"] and ex["cusip"] == lab["cusip"]) or \
                (lab["isin"] and ex["isin"] == lab["isin"]) or False
        for f in ("quantity", "settlement_date", "deadline", "counterparty"):
            if lab[f] is not None:
                fields[f][0] += 1
                fields[f][1] += ex[f] == lab[f]
        want, got = expected_route(lab), d["route"]
        if lab["ssi_change"]:
            ssi[0] += 1
            ssi[1] += got == "SSI_CALLBACK"
        elif got == "SSI_CALLBACK":
            ssi_fp.append(e["email_id"])
        if got == want and (got != "JIRA" or ex["category"] == lab["category"]):
            outcome["correct"] += 1
            if got == "JIRA":
                prio[0] += 1
                prio[1] += d["priority"] == lab["priority"]
        elif got == "HUMAN_REVIEW" and want != "SSI_CALLBACK":
            outcome["deferred to a human"] += 1
        elif got == "SSI_CALLBACK" and want != "SSI_CALLBACK":
            outcome["extra call-back (safe)"] += 1
        else:
            outcome["wrong"] += 1
            unsafe.append(dict(email_id=e["email_id"], subject=e["subject"], label=lab["category"],
                               variant=lab["variant"], got_category=ex["category"], route=got, expected=want))
    per_class = {}
    for c in CATEGORIES:
        support = sum(conf[c].values())
        predicted = sum(conf[t][c] for t in conf)
        tp = conf[c][c]
        per_class[c] = dict(support=support, precision=round(tp / predicted, 4) if predicted else None,
                            recall=round(tp / support, 4) if support else None)
    correct_cat = sum(conf[c][c] for c in CATEGORIES)
    routes = Counter(r["decision"]["route"] for r in results)
    return dict(
        extractor=extractor_name,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        n=n,
        category_accuracy=round(correct_cat / n, 4),
        category_correct=correct_cat,
        by_style={k: dict(n=v[0], correct=v[1], accuracy=round(v[1] / v[0], 4)) for k, v in by_style.items()},
        per_class=per_class,
        confusion={t: dict(conf[t]) for t in CATEGORIES},
        fields={f: dict(n=v[0], correct=v[1], accuracy=round(v[1] / v[0], 4) if v[0] else None)
                for f, v in fields.items()},
        ssi=dict(changes=ssi[0], routed_to_callback=ssi[1], recall=round(ssi[1] / ssi[0], 4) if ssi[0] else None,
                 false_positives=len(ssi_fp)),
        routes=dict(routes),
        outcome=dict(outcome),
        auto_handled=round((routes["JIRA"] + routes["FYI"]) / n, 4),
        priority=dict(n=prio[0], correct=prio[1], accuracy=round(prio[1] / prio[0], 4) if prio[0] else None),
        wrong=unsafe,
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["rules", "openai"], default="rules")
    args = ap.parse_args(argv)
    extractor = RuleExtractor() if args.extractor == "rules" else OpenAIExtractor()
    emails, labels = load()
    tr = Triage(extractor=extractor)
    results = [tr.process(e) for e in emails]
    m = score(emails, labels, results, args.extractor)
    out = ROOT / "reports" / f"benchmark_{args.extractor}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(m, indent=2))
    print(f"\n{m['n']} emails, extractor={m['extractor']}")
    print(f"category accuracy   {m['category_correct']}/{m['n']} = {m['category_accuracy']:.1%}")
    for k, v in m["by_style"].items():
        print(f"   {k:<6} {v['correct']}/{v['n']} = {v['accuracy']:.1%}")
    print("fields:")
    for f, v in m["fields"].items():
        print(f"   {f:<16} {v['correct']}/{v['n']} = {v['accuracy']:.1%}")
    s = m["ssi"]
    print(f"SSI changes routed to call-back  {s['routed_to_callback']}/{s['changes']}  (false positives {s['false_positives']})")
    print(f"routes   {m['routes']}")
    print(f"outcome  {m['outcome']}")
    print(f"auto-handled {m['auto_handled']:.1%}   priority on correct tickets {m['priority']['correct']}/{m['priority']['n']}")
    if m["wrong"]:
        print("wrong:")
        for w in m["wrong"]:
            print(f"   {w['email_id']} [{w['label']}/{w['variant']}] -> {w['got_category']} via {w['route']}: {w['subject'][:60]}")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
