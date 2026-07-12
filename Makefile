.PHONY: test check smoke

PYTHON ?= python

test:
	$(PYTHON) -m pytest -q

check: test
	$(PYTHON) manage.py check --settings=zhongbei_info.settings_test
	$(PYTHON) manage.py makemigrations --check --dry-run --settings=zhongbei_info.settings_test
	$(PYTHON) manage.py research_agent_eval --json --settings=zhongbei_info.settings_test

smoke:
	$(PYTHON) manage.py research_agent_smoke --json
