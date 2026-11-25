from conftest import email
from triage.controls import decide
from triage.extract import Extraction


def ex(**kw):
    base = dict(category="TRADE_QUERY", confidence=0.95, trade_ids=["T7381532"], cusip="037833100", isin=None,
                quantity=25000, settlement_date="2026-11-19", deadline=None, counterparty="Kestrel Prime")
    base.update(kw)
    return Extraction(**base)


def test_ssi_wins_over_a_confident_classifier():
    e = email("Allocation T7381532", "Please check the split. Also our bank details have changed, account 99887766.")
    d = decide(e, ex())
    assert d.route == "SSI_CALLBACK" and d.ssi_flags


def test_lookalike_sender_goes_to_callback_even_if_harmless():
    e = email("Allocation T7381532", "Please check the split.", from_addr="ops@kestre1prime.example")
    assert decide(e, ex()).route == "SSI_CALLBACK"


def test_low_confidence_goes_to_a_person():
    d = decide(email("hmm", "can you look at this"), ex(confidence=0.6))
    assert d.route == "HUMAN_REVIEW" and "confidence" in d.reasons[0]


def test_bad_cusip_goes_to_a_person():
    d = decide(email("T7381532", "x"), ex(cusip="037833109"))
    assert d.route == "HUMAN_REVIEW" and "check digit" in d.validation_errors[0]


def test_fail_priority_never_below_high():
    d = decide(email("fail", "x", received="2026-11-18T09:00:00"),
               ex(category="SETTLEMENT_FAIL", settlement_date="2026-11-24"))
    assert d.route == "JIRA" and d.priority == "High"


def test_trade_query_priority_from_t_plus_one():
    d = decide(email("q", "x", received="2026-11-18T09:00:00"), ex(settlement_date="2026-11-19"))
    assert d.priority == "High"


def test_noise_is_fyi():
    assert decide(email("Webinar", "register here"), ex(category="OTHER", confidence=0.9, trade_ids=[])).route == "FYI"
