PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: verify verify-deploy

verify:
	$(PYTHON) scripts/verify.py

# Keep the public web-service gate deterministic on Render's Python runtime.
# The provider-independent `verify` target remains the full Python + Node gate.
verify-deploy:
	$(PYTHON) -m pytest -q
	$(PYTHON) -m mypy --strict standing
	$(PYTHON) -m standing memory-proof
