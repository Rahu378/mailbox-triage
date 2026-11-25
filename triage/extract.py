"""Classify an email and pull out trade ID, CUSIP/ISIN, quantity, settlement date.

Two extractors with the same output shape:
  * RuleExtractor: regex + keyword scoring. No API key, deterministic, runs in
    the browser demo, and gives the controls a second opinion on SSI changes.
  * OpenAIExtractor: one structured-output call (strict JSON schema).

Either way the result goes through triage.controls before anything happens.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field

from .calendar import add_bdays

CATEGORIES = ("TRADE_QUERY", "SETTLEMENT_FAIL", "SSI_UPDATE", "CA_ELECTION", "PRICE_CHALLENGE", "OTHER")

KNOWN_ORGS = {
    "halden-sec.example": "Halden Securities", "northgatecm.example": "Northgate Capital Markets",
    "kestrelprime.example": "Kestrel Prime", "oakmontlowe.example": "Oakmont & Lowe",
    "sablestreet.example": "Sable Street Partners", "marlowexec.example": "Marlow Agency Execution",
    "meridiancustody.example": "Meridian Custody", "atlastrust.example": "Atlas Trust",
}
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "JNJ", "KO", "META", "ORCL", "CSCO", "SAP", "ASML", "AZN",
           "SPY", "LQD"]


@dataclass
class Span:
    field: str
    start: int
    end: int
    text: str
    where: str = "body"


@dataclass
class Extraction:
    category: str
    confidence: float
    trade_ids: list = field(default_factory=list)
    cusip: str | None = None
    isin: str | None = None
    quantity: int | None = None
    settlement_date: str | None = None
    deadline: str | None = None
    counterparty: str | None = None
    ssi_change_detected: bool = False
    summary: str = ""
    requested_action: str = ""
    scores: dict = field(default_factory=dict)
    spans: list = field(default_factory=list)
    extractor: str = "rules"

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------- checks
def cusip_valid(c: str) -> bool:
    if not re.fullmatch(r"[0-9A-Z]{9}", c or ""):
        return False
    total = 0
    for i, ch in enumerate(c[:8]):
        v = int(ch) if ch.isdigit() else ord(ch) - 55
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10 == int(c[8])


def isin_valid(s: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{9}[0-9]", s or ""):
        return False
    digits = "".join(str(int(ch, 36)) for ch in s[:11])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(s[11])


# ----------------------------------------------------------------- parsing
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], start=1)}
DATE_RX = (r"(?P<d>\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2}|\d{1,2}-[A-Za-z]{3}-\d{4}|"
           r"(?:mon|tue|wed|thu|fri)[a-z]* \d{1,2}(?:st|nd|rd|th)? [A-Za-z]{3}[a-z]*|"
           r"[A-Za-z]{3}[a-z]* \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?|today(?: \(t\+0\))?|tomorrow|t\+[01])")


def parse_date(text: str, received: dt.datetime) -> dt.date | None:
    t = text.strip().lower()
    base = received.date()
    if t.startswith("today") or t == "t+0":
        return base
    if t in ("tomorrow", "t+1"):
        return add_bdays(base, 1)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return dt.date(*map(int, m.groups()))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        y = int(m.group(3)) if m.group(3) else base.year
        y = y + 2000 if y < 100 else y
        return dt.date(y, int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"(\d{1,2})-([a-z]{3})-(\d{4})", t)
    if m and m.group(2) in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    m = re.fullmatch(r"(?:mon|tue|wed|thu|fri)[a-z]* (\d{1,2})(?:st|nd|rd|th)? ([a-z]{3})[a-z]*", t)
    if m and m.group(2) in MONTHS:
        return dt.date(base.year, MONTHS[m.group(2)], int(m.group(1)))
    m = re.fullmatch(r"([a-z]{3})[a-z]* (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?", t)
    if m and m.group(1) in MONTHS:
        return dt.date(int(m.group(3) or base.year), MONTHS[m.group(1)], int(m.group(2)))
    return None


def parse_qty(text: str) -> int | None:
    t = text.lower().replace(",", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(mm|m|k)?", t)
    if not m:
        return None
    v = float(m.group(1)) * {"mm": 1e6, "m": 1e6, "k": 1e3, None: 1}[m.group(2)]
    return int(round(v))


def strip_disclaimer(body: str) -> str:
    return re.split(r"\n\s*This email and any attachments are confidential", body)[0]


def lookalike_of(domain: str) -> str | None:
    """Return the real counterparty if `domain` is one or two edits away from a known one."""
    def dist(a, b):
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]
    for known, org in KNOWN_ORGS.items():
        if domain != known and dist(domain, known) <= 2:
            return org
    return None


SSI_CHANGE_RX = re.compile(
    r"(?:new|updated?|chang(?:e|ed|es)|moved|amended)\b[^.\n]{0,40}\b(?:bank details|account number|settlement account|"
    r"wire instructions|settlement instructions|ssis?|beneficiary|payment details|bank account)|"
    r"(?:bank details|settlement instructions|ssis?|wire instructions|bank account)\b[^.\n]{0,40}\b(?:have changed|changed|"
    r"change effective|update|updated|are changing)", re.I)


def detect_ssi_change(subject: str, body: str) -> list[str]:
    """Reasons this email might be changing where money or securities go. Defense in depth: this runs
    whatever the classifier said."""
    reasons = []
    text = f"{subject}\n{body}"
    if SSI_CHANGE_RX.search(text):
        reasons.append("asks to change settlement / bank details")
    if re.search(r"\b(?:ABA|SWIFT|BIC|IBAN)\b", text) and re.search(r"\baccount\b", text, re.I):
        reasons.append("contains bank routing details")
    # anything that redirects where money or securities go, however it's worded
    if re.search(r"switched (?:custodians?|banks?|agents?)|new (?:custodian|agent|bank)\b|"
                 r"(?:going forward|from (?:now|monday|today)).{0,60}\b(?:send|pay|wire|deliver|remit)\b", text, re.I) \
            and re.search(r"\b(?:acct|account|a/c)\b", text, re.I):
        reasons.append("redirects payments or deliveries to a new account")
    return reasons


# ----------------------------------------------------------------- rules
KEYWORDS = {
    "SETTLEMENT_FAIL": [(r"\bfail(?:ed|ing|s)?\b", 3), (r"failed to settle", 4), (r"\bshort\b", 2),
                        (r"didn'?t settle|did not settle|still open", 3), (r"pending delivery", 4),
                        (r"buy-in|close-out", 2), (r"fail notification", 5), (r"settlements? (?:can )?chase", 2)],
    "SSI_UPDATE": [(r"settlement instructions|\bssis?\b", 5), (r"bank details|wire instructions|settlement account", 5),
                   (r"\baccount number\b|\baba\b|\bswift\b|\bbic\b|\biban\b|beneficiary", 2),
                   (r"dtc participant|agent bank|static data", 3)],
    "CA_ELECTION": [(r"\belection\b|\belect\b", 4), (r"corporate action", 3),
                    (r"tender offer|rights issue|reinvestment|consent solicitation|exchange offer", 3),
                    (r"response deadline", 3), (r"eligible position", 2)],
    "PRICE_CHALLENGE": [(r"price challenge|\bchallenge\b", 4), (r"\bstale\b|vendor close|evaluated price", 3),
                        (r"before nav|\bnav\b", 2), (r"last trade", 1)],
    "TRADE_QUERY": [(r"trade query|allocation|account split|\bconfirm\b|affirmation|affirm|booking|blotter|mismatch|"
                     r"quantity difference|commission|net amount|average", 3), (r"price/qty|confirm the price", 2)],
    "OTHER": [(r"automatic reply|out of (?:the )?office", 6), (r"unsubscribe|webinar|register here|market wrap", 5),
              (r"lunch|fire drill|offsite|sandwich", 4)],
}


class RuleExtractor:
    name = "rules"

    def extract(self, email: dict) -> Extraction:
        subject, raw = email["subject"], email["body"]
        body = strip_disclaimer(raw)
        received = dt.datetime.fromisoformat(email["received_at"])
        scores = {c: 0.0 for c in CATEGORIES}
        for cat, rules in KEYWORDS.items():
            for rx, w in rules:
                scores[cat] += 2 * w * len(re.findall(rx, subject, re.I)) + w * min(2, len(re.findall(rx, body, re.I)))
        # auto-replies are noise whatever they quote
        if re.match(r"\s*(?:automatic reply|auto(?:matic)?[- ]?reply|out of office)", subject, re.I):
            scores["OTHER"] += 40
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        (top, s1), (_, s2) = ranked[0], ranked[1]
        if s1 < 4:
            top, conf = "OTHER", 0.55
        else:
            conf = round(min(0.99, 0.5 + 0.5 * (s1 - s2) / s1 + (0.1 if s1 >= 10 else 0)), 3)
        ex = Extraction(category=top, confidence=conf, scores=scores)

        def span(fieldname, m, group=0):
            ex.spans.append(Span(fieldname, m.start(group), m.end(group), m.group(group)))

        for where, text in (("subject", subject), ("body", raw)):
            for m in re.finditer(r"\bT\d{7}\b", text):
                if m.group(0) not in ex.trade_ids:
                    ex.trade_ids.append(m.group(0))
                ex.spans.append(Span("trade_id", m.start(), m.end(), m.group(0), where))
        m = re.search(r"CUSIP[:#\s]*([0-9A-Z]{9})\b", raw)
        if m:
            ex.cusip = m.group(1)
            span("cusip", m, 1)
        m = re.search(r"(?:ISIN[:#\s]*)?\b([A-Z]{2}[0-9A-Z]{9}[0-9])\b", raw)
        if m and (isin_valid(m.group(1)) or raw[max(0, m.start() - 6):m.start(1)].upper().startswith("ISIN")):
            ex.isin = m.group(1)
            span("isin", m, 1)
        qty_rx = [
            r"(?:quantity|qty|eligible position|total)\s*[:=]?\s*([\d][\d.,]*\s*(?:mm|k)?)\b",
            r"\b([\d][\d.,]*\s*(?:mm|k)?)\s*(?:shs|shares|units)\b",
            r"\b([\d][\d.,]*(?:mm|k)?)\s+(?:" + "|".join(TICKERS) + r")\b",
            r"(?:shows|with|short on [^,]+,)\s+([\d][\d.,]*(?:mm|k)?)\b",
            r"\b([\d][\d.,]*(?:mm|k)?)\s*@\s*\d",  # "23,800 @ 103.99"
        ]
        for rx in qty_rx:
            m = re.search(rx, raw, re.I)
            if m:
                q = parse_qty(m.group(1))
                if q and q >= 10:
                    ex.quantity = q
                    span("quantity", m, 1)
                    break
        sd = re.search(r"(?:settles|settle|settlement date|contractual settlement date|value date|\bSD\b|due|"
                       r"was due|settling)\s*[:\-]?\s*(?:on\s+)?" + DATE_RX, raw, re.I)
        if sd:
            d = parse_date(sd.group("d"), received)
            if d:
                ex.settlement_date = d.isoformat()
                span("settlement_date", sd, "d")
        dl = re.search(r"(?:response deadline|deadline|respond by|no later than)\s*[:\-]?\s*" + DATE_RX, raw, re.I)
        if dl:
            d = parse_date(dl.group("d"), received)
            if d:
                ex.deadline = d.isoformat()
                span("deadline", dl, "d")
        # counterparty: who is on the other side, not who forwarded it
        addrs = re.findall(r"[\w.\-]+@([\w.\-]+\.example)", email["from_addr"] + "\n" + raw)
        org = None
        for dom in addrs:
            if dom in KNOWN_ORGS:
                org = KNOWN_ORGS[dom]
                break
            look = lookalike_of(dom)
            if look:
                org = look
                break
        m = re.search(r"Counterparty(?: is|:)\s*([A-Z][\w&. ]+?)(?:\.|\n|$)", raw)
        if m and ex.category in ("SETTLEMENT_FAIL", "TRADE_QUERY"):
            org = m.group(1).strip()
        if not org:
            for name in set(KNOWN_ORGS.values()):
                if name in raw:
                    org = name
                    break
        ex.counterparty = org if ex.category not in ("PRICE_CHALLENGE", "OTHER") else None
        ex.ssi_change_detected = bool(detect_ssi_change(subject, body)) or ex.category == "SSI_UPDATE"
        ex.summary = subject
        return ex


# ----------------------------------------------------------------- OpenAI
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "confidence", "trade_ids", "cusip", "isin", "quantity", "settlement_date", "deadline",
                 "counterparty", "ssi_change_detected", "summary", "requested_action"],
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "confidence": {"type": "number", "description": "0 to 1"},
        "trade_ids": {"type": "array", "items": {"type": "string"}},
        "cusip": {"type": ["string", "null"]},
        "isin": {"type": ["string", "null"]},
        "quantity": {"type": ["integer", "null"]},
        "settlement_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "deadline": {"type": ["string", "null"], "description": "YYYY-MM-DD, for corporate action elections"},
        "counterparty": {"type": ["string", "null"]},
        "ssi_change_detected": {"type": "boolean"},
        "summary": {"type": "string"},
        "requested_action": {"type": "string"},
    },
}


class OpenAIExtractor:
    name = "openai"

    def __init__(self, client=None, model: str | None = None, prompt_path=None):
        from .config import OPENAI_MODEL, ROOT

        self.model = model or OPENAI_MODEL
        self.system = open(prompt_path or ROOT / "prompts" / "triage_system.md").read()
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self.client = client

    def extract(self, email: dict) -> Extraction:
        user = (f"Received: {email['received_at']}\nFrom: {email['from_name']} <{email['from_addr']}>\n"
                f"Subject: {email['subject']}\n\n{strip_disclaimer(email['body'])}")
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "system", "content": self.system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "triage", "strict": True, "schema": SCHEMA}},
        )
        msg = resp.choices[0].message
        if getattr(msg, "refusal", None):
            raise RuntimeError(f"model refused: {msg.refusal}")
        data = json.loads(msg.content)
        ex = Extraction(**{k: data[k] for k in SCHEMA["required"]}, extractor="openai")
        # second opinion on bank details, whatever the model said
        ex.ssi_change_detected = ex.ssi_change_detected or bool(detect_ssi_change(email["subject"], email["body"]))
        return ex
