import pytest
from sqlalchemy.exc import IntegrityError

from conftest import email
from triage.benchmark import score
from triage.pipeline import Triage
from triage.store import Store


def fail_email(eid, received="2026-11-18T09:00:00"):
    e = email("FAIL NOTIFICATION - T7381532 - AAPL",
              "The following transaction has failed to settle.\n\nClient ref: T7381532\nISIN: US0378331005\n"
              "Quantity: 25,000\nContractual settlement date: 17-Nov-2026\nCounterparty: Kestrel Prime\n",
              from_addr="settlements.notify@meridiancustody.example", received=received)
    e["email_id"] = eid
    return e


def test_follow_up_becomes_a_comment():
    t = Triage()
    a, b = t.process(fail_email("A")), t.process(fail_email("B"))
    assert a["jira_action"] == "created" and b["jira_action"] == "commented"
    assert a["jira_key"] == b["jira_key"]


def test_no_draft_for_ssi_changes():
    r = Triage().process(email("New SSIs", "Our settlement instructions have changed, account 1234567."))
    assert r["decision"]["route"] == "SSI_CALLBACK" and r["draft"] is None


def test_store_and_approval(tmp_path):
    st = Store(f"sqlite:///{tmp_path / 't.db'}")
    Triage(store=st).process(fail_email("A"))
    assert st.query("SELECT status FROM reply_drafts")[0]["status"] == "PENDING_APPROVAL"
    st.approve_draft("A", "rr")
    assert st.query("SELECT status, approved_by FROM reply_drafts")[0] == {"status": "APPROVED", "approved_by": "rr"}
    with pytest.raises(ValueError):
        st.approve_draft("A", "rr")  # already handled


def test_database_refuses_sent_without_approval(tmp_path):
    st = Store(f"sqlite:///{tmp_path / 't.db'}")
    Triage(store=st).process(fail_email("A"))
    with pytest.raises(IntegrityError):
        st.query("UPDATE reply_drafts SET status = 'SENT' WHERE email_id = 'A'")
        with st.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE reply_drafts SET status = 'SENT' WHERE email_id = 'A'")


def test_benchmark_invariants(mail):
    emails, labels = mail
    t = Triage()
    m = score(emails, labels, [t.process(e) for e in emails], "rules")
    assert m["ssi"]["recall"] == 1.0          # every settlement-detail change goes to a call-back
    assert m["outcome"].get("wrong", 0) == 0  # misses are deferred to a person, never misrouted
    assert m["by_style"]["plain"]["accuracy"] == 1.0
    assert m["priority"]["accuracy"] == 1.0
