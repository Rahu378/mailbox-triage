import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TRIAGE_DATA_DIR", ROOT / "data"))
DB_URL = os.getenv("TRIAGE_DB_URL", f"sqlite:///{DATA_DIR / 'triage.db'}")

MAILBOX = "middle.office@harborpeak.example"
FIRM_DOMAIN = "harborpeak.example"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CONFIDENCE_FLOOR = float(os.getenv("TRIAGE_CONFIDENCE_FLOOR", "0.75"))

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "")          # https://<site>.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "MO")

WEEK_START = dt.date(2026, 11, 16)
WEEK_END = dt.date(2026, 11, 20)
