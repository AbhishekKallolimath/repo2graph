.PHONY: install lint format format-check typecheck test test-cov clean

install:
	pip install -e ".[dev,rag,mcp]"

lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

# Mirrors .pre-commit-config.yaml's mypy-strict hook: strict on the modules
# that are actually annotated. See pyproject.toml's [[tool.mypy.overrides]]
# for why the legacy modules are excluded by name instead of by wildcard.
typecheck:
	python -m mypy repo2graph/events.py repo2graph/cache.py repo2graph/auth.py \
		repo2graph/audit.py repo2graph/tasks.py repo2graph/http_server.py

test:
	pytest -q

test-cov:
	pytest --cov=repo2graph --cov-report=term-missing

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
