"""US settlement calendar (Fed holidays) and T+1 urgency.

Thanksgiving is Thursday 26 Nov 2026, so a trade done on Wednesday the 25th
settles on Friday the 27th, not Thursday. That's the kind of thing a naive
"settle_date - today" priority gets wrong.
"""
from __future__ import annotations

import datetime as dt

HOLIDAYS_2026 = {
    dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16), dt.date(2026, 5, 25),
    dt.date(2026, 6, 19), dt.date(2026, 7, 3), dt.date(2026, 9, 7), dt.date(2026, 10, 12),
    dt.date(2026, 11, 11), dt.date(2026, 11, 26), dt.date(2026, 12, 25),
}


def is_business_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_2026


def add_bdays(d: dt.date, n: int) -> dt.date:
    step = 1 if n >= 0 else -1
    k = 0
    while k != n:
        d += dt.timedelta(days=step)
        if is_business_day(d):
            k += step
    return d


def bdays_between(start: dt.date, end: dt.date) -> int:
    """Signed business days from start to end (0 if same day)."""
    if end == start:
        return 0
    sign = 1 if end > start else -1
    a, b = (start, end) if sign == 1 else (end, start)
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if is_business_day(d):
            n += 1
    return sign * n


def settlement_urgency(received: dt.datetime, settle: dt.date | None) -> tuple[str, int | None]:
    """Jira priority from how close settlement is, T+1 world.

    already due or settling today -> Highest, next business day -> High,
    T+2 -> Medium, later -> Low.
    """
    if settle is None:
        return "Medium", None
    gap = bdays_between(received.date(), settle)
    if gap <= 0:
        return "Highest", gap
    if gap == 1:
        return "High", gap
    if gap == 2:
        return "Medium", gap
    return "Low", gap
