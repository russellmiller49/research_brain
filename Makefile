.PHONY: install dev test run demo

install:
	python -m pip install -e .

dev:
	python -m pip install -e ".[dev]"

test:
	PYTHONPATH=src pytest

run:
	PYTHONPATH=src python -m research_memory --no-browser

demo:
	PYTHONPATH=src python scripts/create_demo_library.py --data-dir ./research_memory_data
