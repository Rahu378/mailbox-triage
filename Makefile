.PHONY: mailbox bench test workflow site e2e pages

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

# the Pages site is served from the gh-pages branch, a copy of docs/
pages:
	git subtree split --prefix docs -b gh-pages-tmp
	git push -f origin gh-pages-tmp:gh-pages
	git branch -D gh-pages-tmp
