.PHONY: bootstrap install lint test build run desktop demo licenses sbom benchmark-demo

PYTHON ?= python3.13
VENV ?= .venv-beta

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --require-hashes -r requirements.lock
	$(VENV)/bin/pip install --no-deps -e .
	cd desktop && npm ci

install: bootstrap

lint:
	$(VENV)/bin/python scripts/validate_taxonomy_catalog.py
	$(VENV)/bin/python scripts/generate_taxonomy_types.py --check
	$(VENV)/bin/ruff check src tests scripts
	$(VENV)/bin/ruff format --check src tests scripts
	$(VENV)/bin/mypy src/research_memory
	cd desktop && npm run build
	cd desktop/src-tauri && cargo fmt --all -- --check
	cd desktop/src-tauri && cargo clippy --locked --all-targets -- -D warnings

test:
	$(VENV)/bin/pytest
	cd desktop && npm test
	cd desktop/src-tauri && cargo test --locked

build:
	cd desktop && npm run build
	cd desktop/src-tauri && cargo check --locked

run:
	$(VENV)/bin/research-memory --legacy-web --no-browser

desktop:
	cd desktop && npm run tauri dev

demo:
	$(VENV)/bin/python scripts/create_demo_library.py --data-dir ./research_memory_data --reset

licenses:
	mkdir -p artifacts
	$(VENV)/bin/python scripts/check_licenses.py --output artifacts/licenses.json

sbom:
	mkdir -p artifacts
	$(VENV)/bin/python scripts/generate_sbom.py --output artifacts/sbom-complete.cdx.json

benchmark-demo: demo
	RESEARCH_MEMORY_EMBEDDING_BACKEND=hash $(VENV)/bin/python scripts/run_retrieval_benchmark.py \
		--data-dir ./research_memory_data \
		--queries benchmarks/queries.example.jsonl \
		--output artifacts/demo-retrieval-report.json
