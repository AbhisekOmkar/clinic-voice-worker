.PHONY: install dev run download-models test lint format console

install:
	poetry install

download-models:
	poetry run python -m app.worker download-files

dev:
	poetry run python -m app.worker dev

run:
	poetry run python -m app.worker start

console:
	poetry run python -m app.worker console

test:
	poetry run pytest -q

lint:
	poetry run ruff check app/ tests/ evals/

format:
	poetry run black app/ tests/ evals/ && poetry run ruff check --fix app/ tests/ evals/

eval:
	poetry run python -m evals.run --scenarios evals/scenarios

eval-latency:
	poetry run python -m evals.latency_probe
