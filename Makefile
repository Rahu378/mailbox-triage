.PHONY: mailbox bench test workflow site e2e

mailbox:
	python -m triage.mailbox

bench:
	python -m triage.benchmark

test:
	python -m pytest -q

workflow:
	python n8n/build.py

site:
	python -m triage.export_site

e2e:
	./n8n/e2e/run_e2e.sh
