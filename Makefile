# Every target here is a *sensor*: something that checks the work after it was done.
# `make check` is the single gate referenced by AGENTS.md.

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: setup check test lint type lint-arch schemas check-schemas evals demo doctor clean

setup: ## one-time: create venv, install package + dev deps
	python3 -m venv .venv
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"

check: lint type lint-arch check-schemas test evals ## full gate — must be green before any commit

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

type:
	.venv/bin/mypy

lint-arch:
	.venv/bin/lint-imports --config .importlinter

schemas:
	$(PY) scripts/export_schemas.py

check-schemas:
	$(PY) scripts/export_schemas.py --check

test:
	$(PY) -m pytest

evals:
	$(PY) scripts/run_evals.py --no-write

demo:
	$(PY) -m archery_agent.interfaces.cli demo

doctor:
	$(PY) -m archery_agent.interfaces.cli doctor

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
