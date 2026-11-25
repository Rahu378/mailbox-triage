import datetime as dt

from triage.calendar import add_bdays, bdays_between, settlement_urgency


def test_thanksgiving_is_not_a_settlement_day():
    assert add_bdays(dt.date(2026, 11, 25), 1) == dt.date(2026, 11, 27)
    assert bdays_between(dt.date(2026, 11, 25), dt.date(2026, 11, 27)) == 1


def test_weekend_skipped():
    assert add_bdays(dt.date(2026, 11, 20), 1) == dt.date(2026, 11, 23)


def test_urgency_buckets():
    rec = dt.datetime(2026, 11, 18, 9, 0)
    assert settlement_urgency(rec, dt.date(2026, 11, 17)) == ("Highest", -1)
    assert settlement_urgency(rec, dt.date(2026, 11, 18)) == ("Highest", 0)
    assert settlement_urgency(rec, dt.date(2026, 11, 19)) == ("High", 1)
    assert settlement_urgency(rec, dt.date(2026, 11, 20)) == ("Medium", 2)
    assert settlement_urgency(rec, dt.date(2026, 11, 27)) == ("Low", 6)
