"""The n8n Code nodes and the Python controls must make the same calls."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from triage.controls import decide
from triage.extract import RuleExtractor

ROOT = Path(__file__).resolve().parent.parent


def test_committed_workflows_are_built_from_current_sources(tmp_path):
    before = {p: p.read_text() for p in (ROOT / "n8n").glob("*.json")}
    subprocess.run([sys.executable, str(ROOT / "n8n" / "build.py")], check=True, capture_output=True)
    after = {p: p.read_text() for p in (ROOT / "n8n").glob("*.json")}
    assert before == after, "run python n8n/build.py and commit the result"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_controls_match_python(mail, tmp_path):
    emails, _ = mail
    ex = RuleExtractor()
    cases = []
    for e in emails:
        x = ex.extract(e)
        d = decide(e, x)
        cases.append(dict(
            email={k: e[k] for k in ("email_id", "received_at", "from_name", "from_addr", "subject", "body")},
            extraction={k: getattr(x, k) for k in ("category", "confidence", "trade_ids", "cusip", "isin", "quantity",
                                                  "settlement_date", "deadline", "counterparty", "ssi_change_detected")},
            expected=dict(route=d.route, priority=d.priority, validation_errors=d.validation_errors,
                          ssi_flags=d.ssi_flags)))
    fx = tmp_path / "cases.json"
    fx.write_text(json.dumps(cases))
    r = subprocess.run(["node", "--test", "n8n/code/controls.test.js", "n8n/code/workflow.test.js"], cwd=ROOT,
                       env={"FIXTURES": str(fx), "PATH": __import__("os").environ["PATH"]}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:]
    assert "# fail 0" in r.stdout
