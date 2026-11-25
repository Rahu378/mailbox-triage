import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

from conftest import email
from triage.extract import (OpenAIExtractor, RuleExtractor, cusip_valid, detect_ssi_change, isin_valid, lookalike_of,
                            parse_date, parse_qty)

REC = dt.datetime(2026, 11, 20, 9, 30)  # Friday


@pytest.mark.parametrize("text,want", [
    ("11/23/2026", "2026-11-23"), ("23-Nov-2026", "2026-11-23"), ("Nov 23", "2026-11-23"),
    ("Mon 23 Nov", "2026-11-23"), ("2026-11-23", "2026-11-23"), ("tomorrow", "2026-11-23"), ("T+1", "2026-11-23"),
    ("today", "2026-11-20"),
])
def test_dates(text, want):
    assert parse_date(text, REC).isoformat() == want


@pytest.mark.parametrize("text,want", [("25,000", 25000), ("25k", 25000), ("1.5mm", 1500000), ("400", 400)])
def test_quantities(text, want):
    assert parse_qty(text) == want


def test_check_digits():
    assert cusip_valid("037833100") and not cusip_valid("037833109")
    assert isin_valid("US0378331005") and not isin_valid("US0378331009")


def test_fail_notice_fields():
    e = email("FAIL NOTIFICATION - T7381532 - AAPL",
              "The following transaction has failed to settle.\n\nClient ref: T7381532\nISIN: US0378331005\n"
              "Quantity: 25,000\nContractual settlement date: 19-Nov-2026\nCounterparty: Kestrel Prime\n",
              from_addr="settlements.notify@meridiancustody.example", received="2026-11-20T08:00:00")
    x = RuleExtractor().extract(e)
    assert x.category == "SETTLEMENT_FAIL"
    assert (x.trade_ids, x.isin, x.quantity, x.settlement_date, x.counterparty) == (
        ["T7381532"], "US0378331005", 25000, "2026-11-19", "Kestrel Prime")
    assert {s.field for s in x.spans} >= {"trade_id", "isin", "quantity", "settlement_date"}


def test_out_of_office_quoting_a_fail_is_noise():
    e = email("Automatic reply: FAIL NOTIFICATION - T7381532", "I'm out of the office.\n> failed to settle T7381532")
    assert RuleExtractor().extract(e).category == "OTHER"


def test_hidden_bank_change_is_caught():
    body = ("Can you confirm the allocation on T7381532? Also note we've moved our settlement account: new account "
            "number 4471223344, ABA 026012345.")
    assert detect_ssi_change("Allocation", body)


def test_lookalike_domains():
    assert lookalike_of("ha1den-sec.example") == "Halden Securities"
    assert lookalike_of("halden-sec.example") is None
    assert lookalike_of("research.example") is None


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(choices=[NS(message=NS(content=json.dumps(self.payload), refusal=None))])


def test_openai_extractor_uses_strict_schema_and_second_opinion(tmp_path):
    payload = dict(category="TRADE_QUERY", confidence=0.93, trade_ids=["T7381532"], cusip="037833100", isin=None,
                   quantity=25000, settlement_date="2026-11-23", deadline=None, counterparty="Kestrel Prime",
                   ssi_change_detected=False, summary="qty mismatch", requested_action="check booking")
    comp = FakeCompletions(payload)
    client = NS(chat=NS(completions=comp))
    x = OpenAIExtractor(client=client).extract(email(
        "T7381532", "Qty mismatch on T7381532. Also please note our new bank details: account 12345678, SWIFT ABCDUS33."))
    call = comp.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert call["temperature"] == 0
    assert x.extractor == "openai" and x.quantity == 25000
    assert x.ssi_change_detected  # the model said no, the rules said yes, yes wins
