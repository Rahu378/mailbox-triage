"""Synthetic middle-office shared mailbox, with ground truth.

One week (Mon 16 to Fri 20 Nov 2026) of what lands in middle.office@: broker
trade queries, custodian fail notices, SSI updates (some of them fraudulent),
corporate action election requests, price challenges, and the usual noise.

About one email in eight is deliberately awkward: forwarded chains, a fail
notice quoted inside an out-of-office, bank details slipped into a trade query,
a CUSIP with a typo, a look-alike sender domain, no settlement date at all.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from dataclasses import asdict, dataclass, field

from .calendar import add_bdays, settlement_urgency
from .config import DATA_DIR, FIRM_DOMAIN, MAILBOX

CATEGORIES = ("TRADE_QUERY", "SETTLEMENT_FAIL", "SSI_UPDATE", "CA_ELECTION", "PRICE_CHALLENGE", "OTHER")

# ticker, name, cusip (None for non-US), isin, approx price
SECURITIES = [
    ("AAPL", "Apple Inc", "037833100", "US0378331005", 228.0),
    ("MSFT", "Microsoft Corp", "594918104", "US5949181045", 415.0),
    ("NVDA", "NVIDIA Corp", "67066G104", "US67066G1040", 142.0),
    ("AMZN", "Amazon.com Inc", "023135106", "US0231351067", 205.0),
    ("JPM", "JPMorgan Chase & Co", "46625H100", "US46625H1005", 238.0),
    ("XOM", "Exxon Mobil Corp", "30231G102", "US30231G1022", 118.0),
    ("JNJ", "Johnson & Johnson", "478160104", "US4781601046", 156.0),
    ("KO", "Coca-Cola Co", "191216100", "US1912161007", 64.0),
    ("META", "Meta Platforms Inc", "30303M102", "US30303M1027", 575.0),
    ("ORCL", "Oracle Corp", "68389X105", "US68389X1054", 182.0),
    ("CSCO", "Cisco Systems Inc", "17275R102", "US17275R1023", 58.0),
    ("SAP", "SAP SE", None, "DE0007164600", 228.0),
    ("ASML", "ASML Holding NV", None, "NL0010273215", 668.0),
    ("AZN", "AstraZeneca plc", None, "GB0009895292", 105.0),
    ("SPY", "SPDR S&P 500 ETF Trust", "78462F103", "US78462F1030", 595.0),
    ("LQD", "iShares iBoxx IG Corporate Bond ETF", "464287242", "US4642872422", 109.0),
]
BROKERS = [
    ("Halden Securities", "halden-sec.example", "ha1den-sec.example"),
    ("Northgate Capital Markets", "northgatecm.example", "northgate-cm.example"),
    ("Kestrel Prime", "kestrelprime.example", "kestre1prime.example"),
    ("Oakmont & Lowe", "oakmontlowe.example", "oakmont-lowe.example"),
    ("Sable Street Partners", "sablestreet.example", "sab1estreet.example"),
    ("Marlow Agency Execution", "marlowexec.example", "marlow-exec.example"),
]
CUSTODIANS = [("Meridian Custody", "meridiancustody.example"), ("Atlas Trust", "atlastrust.example")]
PEOPLE = ["Priya", "Daniel", "Sofia", "Marcus", "Hannah", "Kenji", "Olivia", "Tom", "Leah", "Andre"]
SURNAMES = ["Shah", "Okafor", "Lindqvist", "Brennan", "Castillo", "Mori", "Novak", "Reyes", "Whitaker", "Fischer"]
ACCOUNTS = ["HP Global Equity", "HP US Core", "HP Income Builder", "HP Balanced", "HP Tech Leaders"]
FAIL_REASONS = ["insufficient securities", "counterparty short", "SSI mismatch on our side", "late matching",
                "DK'd by counterparty", "cash shortfall at the agent"]
DISCLAIMER = ("\n\nThis email and any attachments are confidential and intended solely for the addressee. "
              "If you have received it in error please notify the sender and delete it.")


@dataclass
class Email:
    email_id: str
    received_at: str
    from_name: str
    from_addr: str
    to: str
    cc: str
    subject: str
    body: str
    attachments: list = field(default_factory=list)


@dataclass
class Label:
    email_id: str
    category: str
    trade_ids: list
    cusip: str | None
    isin: str | None
    quantity: int | None
    settlement_date: str | None
    deadline: str | None
    counterparty: str | None
    ssi_change: bool
    priority: str | None
    variant: str


class _Gen:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.n = 0
        self.trade_seq = 7_362_000

    # ------------------------------------------------------------- formatting
    def person(self):
        return f"{self.rng.choice(PEOPLE)} {self.rng.choice(SURNAMES)}"

    def addr(self, name, domain):
        first, last = name.split()[0].lower(), name.split()[-1].lower()
        style = self.rng.choice(["{f}.{l}", "{f}{l}", "{fi}{l}", "ops", "settlements"])
        return style.format(f=first, l=last, fi=first[0]) + "@" + domain

    def trade_id(self):
        self.trade_seq += self.rng.randint(3, 400)
        return f"T{self.trade_seq}"

    def qty(self, price):
        usd = self.rng.choice([150_000, 400_000, 900_000, 1_500_000, 2_500_000, 6_000_000])
        q = max(100, int(usd / price / 100) * 100)
        return q

    def fmt_qty(self, q):
        style = self.rng.random()
        if q >= 1_000_000 and q % 100_000 == 0 and style < 0.4:
            return f"{q / 1e6:g}mm"
        if q >= 10_000 and q % 1000 == 0 and style < 0.3:
            return f"{q // 1000}k"
        if style < 0.55:
            return f"{q:,}"
        if style < 0.8:
            return f"{q:,} shs"
        return str(q)

    def fmt_date(self, d: dt.date, received: dt.datetime):
        nxt = add_bdays(received.date(), 1)
        options = [d.strftime("%m/%d/%Y"), d.strftime("%d-%b-%Y"), d.strftime("%b %d").replace(" 0", " "),
                   d.isoformat(), d.strftime("%a %d %b").replace(" 0", " ")]
        if d == received.date():
            options += ["today", "today (T+0)"]
        if d == nxt:
            options += ["tomorrow", "T+1"]
        return self.rng.choice(options)

    def received(self):
        day = dt.date(2026, 11, 16) + dt.timedelta(days=self.rng.randint(0, 4))
        minute = int(self.rng.triangular(7 * 60 + 30, 18 * 60 + 30, 10 * 60))
        return dt.datetime.combine(day, dt.time(minute // 60, minute % 60, self.rng.randint(0, 59)))

    def sec(self, us_only=False):
        pool = [s for s in SECURITIES if s[2]] if us_only else SECURITIES
        return self.rng.choice(pool)

    def sig(self, name, org):
        return self.rng.choice([
            f"\n\nThanks,\n{name}\n{org}",
            f"\n\nRegards\n{name} | {org} | Operations",
            f"\n\nBest,\n{name.split()[0]}",
            f"\n\n{name}\n{org}\nSent from my iPhone",
        ])

    def new(self, received, from_name, from_addr, subject, body, attachments=None, cc=""):
        self.n += 1
        return Email(email_id=f"MSG-{self.n:05d}", received_at=received.isoformat(), from_name=from_name,
                     from_addr=from_addr, to=MAILBOX, cc=cc, subject=subject, body=body,
                     attachments=attachments or [])

    def label(self, email, category, *, trade_ids=(), cusip=None, isin=None, quantity=None, settle=None,
              deadline=None, counterparty=None, ssi=False, variant="plain"):
        rec = dt.datetime.fromisoformat(email.received_at)
        if ssi or category == "OTHER":
            prio = None
        elif category == "SETTLEMENT_FAIL":
            p, _ = settlement_urgency(rec, settle)
            prio = "Highest" if p == "Highest" else "High"
        elif category == "CA_ELECTION":
            p, _ = settlement_urgency(rec, deadline)
            prio = "Highest" if p == "Highest" else ("High" if p == "High" else "Medium")
        elif category == "PRICE_CHALLENGE":
            prio = "Medium"
        else:
            prio, _ = settlement_urgency(rec, settle)
        return Label(email_id=email.email_id, category=category, trade_ids=list(trade_ids), cusip=cusip, isin=isin,
                     quantity=quantity, settlement_date=settle.isoformat() if settle else None,
                     deadline=deadline.isoformat() if deadline else None, counterparty=counterparty, ssi_change=ssi,
                     priority=prio, variant=variant)

    # ------------------------------------------------------------- categories
    def trade_query(self, hard=False):
        rec = self.received()
        broker, dom, _ = self.rng.choice(BROKERS)
        name = self.person()
        t, sname, cusip, isin, px = self.sec()
        tid = self.trade_id()
        q = self.qty(px)
        settle = add_bdays(rec.date(), self.rng.choice([0, 1, 1, 1, 2]))
        sd = self.fmt_date(settle, rec)
        ident = f"CUSIP {cusip}" if cusip and self.rng.random() < 0.6 else f"ISIN {isin}"
        side = self.rng.choice(["buy", "sell"])
        v = self.rng.randrange(4)
        if v == 0:
            subj = f"Trade query - {t} {side.upper()} {self.fmt_qty(q)}"
            body = (f"Hi team,\n\nWe're seeing a quantity difference on {tid}. Our booking shows {self.fmt_qty(q)} {t} "
                    f"({ident}) at {px * self.rng.uniform(.99, 1.01):.2f}; your allocation came through with "
                    f"{self.fmt_qty(q + self.rng.choice([100, 500, 1000]))}. Trade settles {sd}.\n\nCan you check "
                    f"and confirm which is right?")
        elif v == 1:
            subj = f"RE: Allocation {t} - {tid}"
            body = (f"Hello,\n\nCould you send the account split for the {t} {side} ({ident})? Total {self.fmt_qty(q)}, "
                    f"settlement date {sd}. We have it booked to {self.rng.choice(ACCOUNTS)} only and the PM says "
                    f"it should be split across two funds.")
        elif v == 2:
            subj = f"Confirm mismatch {tid}"
            body = (f"Team - our confirm for {tid} doesn't match your affirmation in CTM. Net amount is off by "
                    f"{self.rng.randint(120, 4800):,} USD, looks like commission. {self.fmt_qty(q)} {t}, {ident}, SD {sd}. "
                    f"Please review before cut-off.")
        else:
            subj = f"{t} trade - price/qty check"
            body = (f"Hi,\n\nQuick one on today's {t} {side}: ref {tid}, {self.fmt_qty(q)} @ "
                    f"{px * self.rng.uniform(.99, 1.01):.4f}. {ident}. Value date {sd}. Can you confirm the price on "
                    f"your side? Our blotter has a different average.")
        variant, ssi = "plain", False
        if hard and self.rng.random() < 0.5:
            # bank details slipped into an ordinary trade query
            body += ("\n\nAlso, for this and future trades please note we've moved our settlement account: new "
                     f"account number 4471{self.rng.randint(100000, 999999)}, ABA 0260{self.rng.randint(10000, 99999)}. "
                     "Please update your records.")
            variant, ssi = "hidden_ssi_change", True
        elif hard:
            # forwarded internally with a comment on top
            fwd = self.person()
            body = (f"Can someone pick this up? PM is asking.\n\n{fwd}\n\n---------- Forwarded message ---------\n"
                    f"From: {name} <{self.addr(name, dom)}>\nSubject: {subj}\n\n{body}")
            subj = "FW: " + subj
            name, dom = fwd, FIRM_DOMAIN
            variant = "forwarded"
        e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker) + DISCLAIMER)
        lab = self.label(e, "TRADE_QUERY", trade_ids=[tid], cusip=cusip if "CUSIP" in ident else None,
                         isin=isin if "ISIN" in ident else None, quantity=q, settle=settle, counterparty=broker,
                         ssi=ssi, variant=variant)
        return e, lab

    def settlement_fail(self, hard=False):
        rec = self.received()
        cust, cdom = self.rng.choice(CUSTODIANS)
        broker, bdom, _ = self.rng.choice(BROKERS)
        t, sname, cusip, isin, px = self.sec()
        tid = self.trade_id()
        q = self.qty(px)
        settle = add_bdays(rec.date(), self.rng.choice([-2, -1, -1, 0, 0]))
        reason = self.rng.choice(FAIL_REASONS)
        v = self.rng.randrange(3)
        variant = "plain"
        if v == 0:
            name = f"{cust} Settlements"
            frm = f"settlements.notify@{cdom}"
            subj = f"FAIL NOTIFICATION - {tid} - {t}"
            body = (f"The following transaction has failed to settle.\n\nClient ref: {tid}\nSecurity: {sname}\n"
                    f"ISIN: {isin}\nQuantity: {q:,}\nContractual settlement date: {settle.strftime('%d-%b-%Y')}\n"
                    f"Counterparty: {broker}\nFail reason: {reason}\n\nPlease contact your counterparty. Buy-in rules "
                    f"apply after the CSDR/close-out window.")
            ident = ("isin", isin)
            cp = broker
            sd_text = None
        elif v == 1:
            name = self.person()
            frm = self.addr(name, bdom)
            sd_text = self.fmt_date(settle, rec)
            subj = self.rng.choice([f"{t} failing - {tid}", f"Pending delivery {t}", f"Fail: {tid}"])
            body = (f"Hi,\n\nHeads up that we're short on {tid}, {self.fmt_qty(q)} {t} due {sd_text}. "
                    f"{'CUSIP ' + cusip if cusip else 'ISIN ' + isin}. We expect to deliver "
                    f"{self.rng.choice(['tomorrow morning', 'by end of day', 'once our borrow comes in'])}. "
                    "Sorry for the hassle.")
            ident = ("cusip", cusip) if cusip else ("isin", isin)
            cp = broker
            name_org = broker
            body += self.sig(name, name_org)
        else:
            name = self.person()
            frm = self.addr(name, FIRM_DOMAIN)
            sd_text = self.fmt_date(settle, rec)
            subj = f"{t} didn't settle?"
            body = (f"Custody report shows {tid} ({self.fmt_qty(q)} {t}, {'CUSIP ' + cusip if cusip else 'ISIN ' + isin}) "
                    f"still open, it was due {sd_text}. Counterparty is {broker}. Can settlements chase?")
            ident = ("cusip", cusip) if cusip else ("isin", isin)
            cp = broker
        if hard:
            # an out-of-office that quotes the fail notice: it's noise, not a fail
            ooo = self.person()
            body = (f"I'm out of the office until Monday with limited access to email. For urgent settlement issues "
                    f"please contact the desk on the shared line.\n\n{ooo}\n\n> {subj}\n> " + body.replace("\n", "\n> "))
            subj = f"Automatic reply: {subj}"
            e = self.new(rec, ooo, self.addr(ooo, FIRM_DOMAIN), subj, body)
            return e, self.label(e, "OTHER", variant="ooo_quoting_fail")
        e = self.new(rec, name, frm, subj, body + DISCLAIMER)
        lab = self.label(e, "SETTLEMENT_FAIL", trade_ids=[tid], quantity=q, settle=settle, counterparty=cp,
                         variant=variant, **{ident[0]: ident[1]})
        return e, lab

    def ssi_update(self, hard=False):
        rec = self.received()
        broker, dom, lookalike = self.rng.choice(BROKERS)
        name = self.person()
        eff = add_bdays(rec.date(), self.rng.randint(1, 5))
        variant = "plain"
        if hard:
            dom = lookalike
            variant = "lookalike_domain"
            subj = self.rng.choice(["URGENT - change of bank details", "Updated wire instructions - action today",
                                    "IMPORTANT: new settlement account"])
            body = (f"Dear Operations,\n\nDue to an internal audit our bank details have changed with immediate "
                    f"effect. Please use the following for all payments and DVP settlements today:\n\n"
                    f"Beneficiary: {broker}\nBank: First Coastal Bank\nAccount: 88{self.rng.randint(10**7, 10**8 - 1)}\n"
                    f"SWIFT: FCBKUS{self.rng.choice(['33', '44', '3N'])}\n\nPlease confirm once updated. Do not call "
                    f"the old number, it is being decommissioned.")
        else:
            subj = self.rng.choice([f"Updated SSIs effective {eff.strftime('%d %b')}", "Standing settlement instructions update",
                                    f"{broker} - new DTC instructions"])
            body = (f"Hello,\n\nPlease note our standing settlement instructions for US equities change effective "
                    f"{eff.strftime('%m/%d/%Y')}:\n\nDTC participant: {self.rng.randint(100, 9999):04d}\nAgent bank: "
                    f"{self.rng.choice(['Meridian Custody', 'Atlas Trust'])}\nAccount: {self.rng.randint(10**6, 10**7)}\n\n"
                    f"The updated SSI is also published in ALERT. Please update your static data.")
        e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker) + DISCLAIMER,
                     attachments=["SSI_letter_signed.pdf"] if not hard else [])
        return e, self.label(e, "SSI_UPDATE", counterparty=broker, ssi=True, variant=variant)

    def ca_election(self, hard=False):
        rec = self.received()
        cust, cdom = self.rng.choice(CUSTODIANS)
        t, sname, cusip, isin, px = self.sec()
        q = self.qty(px)
        deadline = add_bdays(rec.date(), self.rng.choice([1, 1, 2, 3, 5]))
        event = self.rng.choice(["voluntary tender offer", "rights issue", "dividend reinvestment option",
                                 "consent solicitation", "exchange offer"])
        acct = self.rng.choice(ACCOUNTS)
        name = f"{cust} Corporate Actions"
        subj = self.rng.choice([f"ELECTION REQUIRED: {t} {event}", f"Action required - {sname} {event}",
                                f"Reminder: {t} election deadline {deadline.strftime('%d %b')}"])
        body = (f"Corporate action notification\n\nEvent: {event}\nSecurity: {sname} ({'CUSIP ' + cusip if cusip else 'ISIN ' + isin})\n"
                f"Account: {acct}\nEligible position: {q:,}\nResponse deadline: {deadline.strftime('%m/%d/%Y')} 5:00 PM ET\n\n"
                f"Options:\n 1. Participate\n 2. Take no action (default)\n\nPlease submit your election via the portal or "
                f"reply to this email before the deadline.")
        variant = "plain"
        if hard:
            body = ("PM says take the cash option on this one, can you put the election in?\n\n-----Original Message-----\n"
                    + body)
            subj = "FW: " + subj
            name, frm = self.person(), None
            frm = self.addr(name, FIRM_DOMAIN)
            variant = "forwarded"
        else:
            frm = f"corporate.actions@{cdom}"
        e = self.new(rec, name, frm, subj, body + DISCLAIMER)
        lab = self.label(e, "CA_ELECTION", cusip=cusip, isin=None if cusip else isin, quantity=q, deadline=deadline,
                         counterparty=cust, variant=variant)
        return e, lab

    def price_challenge(self, hard=False):
        rec = self.received()
        t, sname, cusip, isin, px = self.sec()
        name = self.person()
        when = add_bdays(rec.date(), -1)
        vendor = px * self.rng.uniform(.95, 1.05)
        last = vendor * self.rng.uniform(1.012, 1.04)
        subj = self.rng.choice([f"Price challenge - {t}", f"{t} close looks stale", f"Challenge: {sname} evaluated price"])
        body = (f"Hi pricing,\n\nThe vendor close we used for {t} ({'CUSIP ' + cusip if cusip and self.rng.random() < .5 else 'ISIN ' + isin}) on "
                f"{when.strftime('%m/%d')} was {vendor:.2f}, but the last trade on the primary exchange was {last:.2f}. "
                f"That's a {abs(last / vendor - 1) * 100:.1f}% gap on a position worth about "
                f"${self.rng.randint(2, 40)}m. Can we challenge it with the vendor before NAV?")
        frm_dom = FIRM_DOMAIN
        variant = "plain"
        if hard:
            body = body.replace("Can we challenge", "No trade ID on this one, it's a holding not a trade. Can we challenge")
            variant = "holding_not_trade"
        e = self.new(rec, name, self.addr(name, frm_dom), subj, body + self.sig(name, "Harbor Peak AM"))
        ident = {"cusip": cusip} if ("CUSIP " + str(cusip)) in body else {"isin": isin}
        return e, self.label(e, "PRICE_CHALLENGE", counterparty=None, variant=variant, **ident)

    def other(self, hard=False):
        rec = self.received()
        name = self.person()
        kind = self.rng.randrange(5)
        if kind == 0:
            subj, body = "Automatic reply: Trade query", (f"I'm out of the office until {self.rng.choice(['Monday', 'Wednesday', 'next week'])} "
                                                            "with limited access to email.")
            dom = self.rng.choice(BROKERS)[1]
        elif kind == 1:
            subj, body = "Weekly market wrap", "Equities finished the week higher led by tech. Rates rallied... unsubscribe"
            dom = "research.example"
        elif kind == 2:
            subj, body = "Lunch order for Thursday's offsite", "Please reply with your sandwich choice by Wednesday."
            dom = FIRM_DOMAIN
        elif kind == 3:
            subj, body = "Webinar invite: T+1 one year on", "Join our panel on settlement efficiency. Register here."
            dom = "events.example"
        else:
            subj, body = "Fire drill this afternoon", "Facilities will run a fire drill at 2pm. Please follow wardens."
            dom = FIRM_DOMAIN
        e = self.new(rec, name, self.addr(name, dom), subj, body)
        return e, self.label(e, "OTHER")

    # ------------------------------------------------------------- loosely worded
    def loose(self, category):
        """How people actually write when they're busy: no keywords, half a sentence, misleading words."""
        rec = self.received()
        broker, dom, _ = self.rng.choice(BROKERS)
        name = self.person()
        t, sname, cusip, isin, px = self.sec()
        tid = self.trade_id()
        q = self.qty(px)
        ident_kind = "cusip" if cusip and self.rng.random() < 0.5 else "isin"
        ident = cusip if ident_kind == "cusip" else isin
        ident_txt = ("CUSIP " if ident_kind == "cusip" else "ISIN ") + ident
        if category == "TRADE_QUERY":
            settle = add_bdays(rec.date(), self.rng.choice([1, 1, 2]))
            sd = self.fmt_date(settle, rec)
            subj, body = self.rng.choice([
                (f"{tid}", f"Can someone look at {tid}? Numbers don't tie out with what we have. {self.fmt_qty(q)} {t}, "
                           f"{ident_txt}, settles {sd}."),
                (f"{t} numbers", f"We have {self.fmt_qty(q)} {t} @ {px:.2f} on {tid}, you have something else. Which one is "
                                 f"right? Settles {sd}. {ident_txt}"),
                (f"before tomorrow - {tid}", f"Before this goes out and turns into a fail, can you double check the account on "
                                             f"{tid}? {self.fmt_qty(q)} {t}, {ident_txt}, settles {sd}."),
            ])
            e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker))
            return e, self.label(e, "TRADE_QUERY", trade_ids=[tid], quantity=q, settle=settle, counterparty=broker,
                                 variant="loose", **{ident_kind: ident})
        if category == "SETTLEMENT_FAIL":
            settle = add_bdays(rec.date(), self.rng.choice([-1, 0]))
            sd = self.fmt_date(settle, rec)
            subj, body = self.rng.choice([
                (f"{t} delivery", f"We couldn't deliver the {t} on {sd} ({tid}), still waiting on our borrow. "
                                  f"Should go out tomorrow. {self.fmt_qty(q)}, {ident_txt}."),
                (f"{tid} not through", f"{tid} hasn't gone through at the depository yet. It was due {sd}. "
                                       f"{self.fmt_qty(q)} {t}, {ident_txt}. We're on it."),
            ])
            e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker))
            return e, self.label(e, "SETTLEMENT_FAIL", trade_ids=[tid], quantity=q, settle=settle, counterparty=broker,
                                 variant="loose", **{ident_kind: ident})
        if category == "CA_ELECTION":
            cust, cdom = self.rng.choice(CUSTODIANS)
            deadline = add_bdays(rec.date(), self.rng.choice([1, 2, 3]))
            subj, body = self.rng.choice([
                (f"{t} rights?", f"Do we want to take up the {sname} rights? {cust} needs an answer by "
                                 f"{deadline.strftime('%m/%d/%Y')}. Position is {q:,}. {ident_txt}"),
                (f"{t} tender - what are we doing", f"{cust} is asking what we're doing with the {t} tender. Cut-off "
                                                    f"{deadline.strftime('%m/%d/%Y')}, we hold {q:,}. {ident_txt}"),
            ])
            me = self.person()
            e = self.new(rec, me, self.addr(me, FIRM_DOMAIN), subj, body)
            return e, self.label(e, "CA_ELECTION", quantity=q, deadline=deadline, counterparty=cust, variant="loose",
                                 **{ident_kind: ident})
        if category == "PRICE_CHALLENGE":
            when = add_bdays(rec.date(), -1)
            vendor = px * self.rng.uniform(.95, 1.05)
            last = vendor * self.rng.uniform(1.015, 1.04)
            subj, body = self.rng.choice([
                (f"{t} mark", f"Is the {t} mark right? We have {vendor:.2f} for {when.strftime('%m/%d')} but the screen "
                              f"says {last:.2f}. {ident_txt}"),
                (f"{t} price", f"Vendor has {t} at {vendor:.2f}, everything else I see is around {last:.2f}. Can we get it "
                               f"looked at before the funds strike? {ident_txt}"),
            ])
            me = self.person()
            e = self.new(rec, me, self.addr(me, FIRM_DOMAIN), subj, body)
            return e, self.label(e, "PRICE_CHALLENGE", variant="loose", **{ident_kind: ident})
        if category == "SSI_UPDATE":
            cust = self.rng.choice(CUSTODIANS)[0]
            subj, body = self.rng.choice([
                ("custodian switch", f"Hi, we've switched custodians, so going forward please send DVP trades to our new "
                                     f"agent at {cust}, acct {self.rng.randint(10**6, 10**7)}. Thanks"),
                ("quick update", f"From Monday please pay {broker} at our new bank, account {self.rng.randint(10**7, 10**8)}. "
                                 "Old one is closing."),
            ])
            e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker))
            return e, self.label(e, "SSI_UPDATE", counterparty=broker, ssi=True, variant="loose")
        # OTHER: thanks-only replies that still mention trade words
        subj, body = self.rng.choice([
            (f"RE: Allocation {t} - {tid}", "Thanks, received. All good now."),
            (f"RE: {t} numbers", "Got it, thanks for sorting. No further action."),
        ])
        e = self.new(rec, name, self.addr(name, dom), subj, body + self.sig(name, broker))
        return e, self.label(e, "OTHER", variant="loose")


def build(seed: int = 5, n: int = 420) -> tuple[list[Email], list[Label]]:
    g = _Gen(seed)
    mix = (["TRADE_QUERY"] * 30 + ["SETTLEMENT_FAIL"] * 24 + ["SSI_UPDATE"] * 9 + ["CA_ELECTION"] * 13
           + ["PRICE_CHALLENGE"] * 11 + ["OTHER"] * 13)
    fn = {"TRADE_QUERY": g.trade_query, "SETTLEMENT_FAIL": g.settlement_fail, "SSI_UPDATE": g.ssi_update,
          "CA_ELECTION": g.ca_election, "PRICE_CHALLENGE": g.price_challenge, "OTHER": g.other}
    emails, labels = [], []
    for _ in range(n):
        cat = g.rng.choice(mix)
        style = g.rng.random()
        if style < 0.18:
            e, lab = g.loose(cat)
        else:
            e, lab = fn[cat](hard=style < 0.18 + 0.12)
        emails.append(e)
        labels.append(lab)
    order = sorted(range(len(emails)), key=lambda i: emails[i].received_at)
    emails = [emails[i] for i in order]
    labels = [labels[i] for i in order]
    for k, (e, lab) in enumerate(zip(emails, labels), start=1):
        e.email_id = lab.email_id = f"MSG-{k:05d}"
    return emails, labels


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("-n", type=int, default=420)
    args = ap.parse_args(argv)
    emails, labels = build(args.seed, args.n)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "mailbox.jsonl").write_text("\n".join(json.dumps(asdict(e)) for e in emails) + "\n")
    (DATA_DIR / "labels.jsonl").write_text("\n".join(json.dumps(asdict(lab)) for lab in labels) + "\n")
    from collections import Counter
    c = Counter(lab.category for lab in labels)
    print(f"{len(emails)} emails -> {DATA_DIR / 'mailbox.jsonl'}")
    for k in CATEGORIES:
        print(f"  {k:<16} {c[k]}")
    print(f"  ssi changes      {sum(lab.ssi_change for lab in labels)}")
    print(f"  loosely worded   {sum(lab.variant == 'loose' for lab in labels)}")
    print(f"  other hard cases {sum(lab.variant not in ('plain', 'loose') for lab in labels)}")


if __name__ == "__main__":
    main()
