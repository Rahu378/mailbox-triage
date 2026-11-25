import pytest

from triage import mailbox


@pytest.fixture(scope="session")
def mail():
    emails, labels = mailbox.build(seed=5, n=420)
    from dataclasses import asdict
    return [asdict(e) for e in emails], {lab.email_id: asdict(lab) for lab in labels}


def email(subject, body, from_addr="ops@kestrelprime.example", received="2026-11-18T10:00:00", name="Ops Team"):
    return dict(email_id="T-1", received_at=received, from_name=name, from_addr=from_addr, to="x", cc="",
                subject=subject, body=body, attachments=[])
