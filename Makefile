PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: verify

verify:
	$(PYTHON) scripts/verify.py
