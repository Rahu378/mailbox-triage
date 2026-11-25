"""Reply drafts. Written for an analyst to approve, edit or bin. Nothing here sends mail.

No draft for SSI changes (you don't reply to a possibly spoofed sender, you call the
number on file), for human-review items (nobody knows what it is yet) or for noise.
"""
from __future__ import annotations


def _first(name: str) -> str:
    n = (name or "").split()[0] if name else ""
    return n if n and n[0].isupper() and "Corporate" not in name and "Settlements" not in name else "team"


def draft_reply(email: dict, ex, decision, ticket: str | None) -> str | None:
    if decision.route != "JIRA":
        return None
    hi = f"Hi {_first(email['from_name'])},"
    ref = ", ".join(ex.trade_ids) or ex.cusip or ex.isin or "this one"
    tail = f"\n\nWe're tracking it under {ticket}." if ticket else ""
    sign = "\n\nThanks,\nMiddle Office\nHarbor Peak Asset Management"
    if ex.category == "SETTLEMENT_FAIL":
        when = f" (contractual settlement {ex.settlement_date})" if ex.settlement_date else ""
        body = (f"Thanks for the heads up on {ref}{when}. Can you confirm the expected delivery time and whether a "
                f"partial is possible today? We need to flag the fail to the PM and to Treasury if it rolls.")
    elif ex.category == "TRADE_QUERY":
        body = (f"Thanks, we're looking at {ref} now and will come back to you before the cut-off"
                + (f" for settlement on {ex.settlement_date}" if ex.settlement_date else "") + ". If your side "
                "changes in the meantime please send the updated confirm.")
    elif ex.category == "CA_ELECTION":
        body = (f"Received, thanks. We'll confirm the election for {ref}"
                + (f" ahead of the {ex.deadline} deadline" if ex.deadline else "") + ". Please don't apply the "
                "default option before you hear from us.")
    elif ex.category == "PRICE_CHALLENGE":
        body = (f"We've raised a challenge on {ref} with the pricing vendor and will update you before the NAV "
                "strike.")
    else:
        return None
    return f"{hi}\n\n{body}{tail}{sign}"
