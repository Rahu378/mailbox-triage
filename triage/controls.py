"""What happens to an email after it's been read. Same rules whichever extractor ran.

Routes:
  SSI_CALLBACK  anything that might change where money or securities go. Never actioned from the
                email. Static data calls the counterparty back on the number already on file.
  HUMAN_REVIEW  low confidence, or the extracted fields don't pass validation.
  FYI           noise (out-of-office, newsletters, thanks-only replies).
  JIRA          everything else, prioritised by how close settlement is.

The order matters: the SSI check runs first and nothing downstream can undo it.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field

from .calendar import bdays_between, is_business_day, settlement_urgency
from .config import CONFIDENCE_FLOOR
from .extract import Extraction, cusip_valid, detect_ssi_change, isin_valid, lookalike_of


@dataclass
class Decision:
    route: str
    priority: str | None = None
    sla_gap_bdays: int | None = None
    reasons: list = field(default_factory=list)
    validation_errors: list = field(default_factory=list)
    ssi_flags: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


REQUIRED = {
    "SETTLEMENT_FAIL": [("trade_ids", "trade ID"), ("settlement_date", "settlement date")],
    "TRADE_QUERY": [("trade_ids", "trade ID")],
    "CA_ELECTION": [("deadline", "election deadline")],
    "PRICE_CHALLENGE": [],
}


def validate(ex: Extraction, received: dt.datetime) -> list[str]:
    errs = []
    for t in ex.trade_ids:
        if not re.fullmatch(r"T\d{7}", t):
            errs.append(f"trade ID {t} isn't in our format")
    if ex.cusip and not cusip_valid(ex.cusip):
        errs.append(f"CUSIP {ex.cusip} fails the check digit")
    if ex.isin and not isin_valid(ex.isin):
        errs.append(f"ISIN {ex.isin} fails the check digit")
    if ex.category in ("SETTLEMENT_FAIL", "TRADE_QUERY", "CA_ELECTION", "PRICE_CHALLENGE") and not (ex.cusip or ex.isin):
        errs.append("no security identifier")
    for key, label in (("settlement_date", "settlement date"), ("deadline", "deadline")):
        v = getattr(ex, key)
        if not v:
            continue
        try:
            d = dt.date.fromisoformat(v)
        except ValueError:
            errs.append(f"{label} {v!r} isn't a date")
            continue
        if not is_business_day(d):
            errs.append(f"{label} {d} isn't a business day")
        if abs(bdays_between(received.date(), d)) > 10:
            errs.append(f"{label} {d} is more than 10 business days from today")
    if ex.quantity is not None and not (0 < ex.quantity < 1_000_000_000):
        errs.append(f"quantity {ex.quantity} looks wrong")
    for key, label in REQUIRED.get(ex.category, []):
        if not getattr(ex, key):
            errs.append(f"missing {label}")
    return errs


def decide(email: dict, ex: Extraction, floor: float = CONFIDENCE_FLOOR) -> Decision:
    received = dt.datetime.fromisoformat(email["received_at"])
    flags = detect_ssi_change(email["subject"], email["body"])
    sender_dom = email["from_addr"].split("@")[-1]
    look = lookalike_of(sender_dom)
    if look:
        flags.append(f"sender domain {sender_dom} is a look-alike of {look}")
    if ex.category == "SSI_UPDATE":
        flags.insert(0, "classified as an SSI update")
    if ex.ssi_change_detected and not flags:
        flags.append("extractor flagged a settlement-instruction change")

    # 1. SSI: always a call-back, never actioned from the email
    if flags:
        return Decision("SSI_CALLBACK", priority="Highest", ssi_flags=flags,
                        reasons=["Possible change to settlement or bank details",
                                 "Call back on the number in static data, not anything in this email"])

    errs = validate(ex, received)
    # 2. noise
    if ex.category == "OTHER" and ex.confidence >= floor:
        return Decision("FYI", reasons=["No action needed"], validation_errors=[])
    # 3. not sure, or the facts don't check out
    if ex.confidence < floor or errs:
        why = []
        if ex.confidence < floor:
            why.append(f"confidence {ex.confidence:.2f} below {floor:.2f}")
        return Decision("HUMAN_REVIEW", reasons=why + errs, validation_errors=errs)
    # 4. ticket, prioritised by settlement proximity
    if ex.category == "SETTLEMENT_FAIL":
        p, gap = settlement_urgency(received, dt.date.fromisoformat(ex.settlement_date))
        p = "Highest" if p == "Highest" else "High"
        why = "Fail: at least High, Highest once it's due"
    elif ex.category == "CA_ELECTION":
        p, gap = settlement_urgency(received, dt.date.fromisoformat(ex.deadline))
        p = p if p in ("Highest", "High") else "Medium"
        why = "Election: driven by the response deadline"
    elif ex.category == "PRICE_CHALLENGE":
        p, gap = "Medium", None
        why = "Price challenge: before the next NAV strike"
    else:
        sd = dt.date.fromisoformat(ex.settlement_date) if ex.settlement_date else None
        p, gap = settlement_urgency(received, sd)
        why = "T+1: priority from business days to settlement"
    return Decision("JIRA", priority=p, sla_gap_bdays=gap, reasons=[why])
