SHELL := /usr/bin/env bash

setup:
	python -m venv .venv
	. .venv/bin/activate && pip install -r embedded/requirements.txt

run:
	. .venv/bin/activate && uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000 --app-dir embedded

test:
	. .venv/bin/activate && pytest -q embedded/tests



lint:
	@echo "Linting placeholder (add flake8/eslint configs as needed)"
