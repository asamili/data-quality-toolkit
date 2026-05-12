# Data Quality Toolkit Makefile

.DEFAULT_GOAL := help

PYTHON ?= python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
PRE_COMMIT := $(PYTHON) -m pre_commit
RUFF := $(PYTHON) -m ruff
BLACK := $(PYTHON) -m black
ISORT := $(PYTHON) -m isort
MYPY := $(PYTHON) -m mypy
CLI := $(PYTHON) -m data_quality_toolkit.cli.main

.PHONY: help install install-dev dev lint format type check \
        test test-unit test-assessment test-cli test-workflow test-exporters \
        demo-happy demo-issues compare-demo clean

help:
	@echo Data Quality Toolkit
	@echo.
	@echo Installation:
	@echo "  install         Install package in editable mode"
	@echo "  install-dev     Install development dependencies"
	@echo "  dev             Install dev deps + pre-commit"
	@echo.
	@echo Code quality:
	@echo "  lint            Run ruff"
	@echo "  format          Run black + isort"
	@echo "  type            Run mypy"
	@echo "  check           Run format + lint + type"
	@echo.
	@echo Testing:
	@echo "  test            Run full test suite with coverage"
	@echo "  test-unit       Run all unit tests without coverage threshold noise"
	@echo "  test-assessment Run assessment unit tests"
	@echo "  test-cli        Run CLI unit tests"
	@echo "  test-workflow   Run workflow unit tests"
	@echo "  test-exporters  Run exporter unit tests"
	@echo.
	@echo Demos:
	@echo "  demo-happy      Run happy-path demo export"
	@echo "  demo-issues     Run issue-showcase demo export"
	@echo "  compare-demo    Build history and compare the happy-path demo"
	@echo.
	@echo Cleanup:
	@echo "  clean           Remove build/test/demo artifacts"

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

dev: install-dev
	$(PRE_COMMIT) install

lint:
	$(RUFF) check src tests

format:
	$(BLACK) src tests
	$(ISORT) src tests

type:
	$(MYPY) src

check: format lint type

test:
	$(PYTEST) --cov=data_quality_toolkit --cov-report=term-missing --cov-report=html

test-unit:
	$(PYTEST) tests/unit/ -v --no-cov

test-assessment:
	$(PYTEST) tests/unit/assessment/ -v --no-cov

test-cli:
	$(PYTEST) tests/unit/cli/ -v --no-cov

test-workflow:
	$(PYTEST) tests/unit/workflow/ -v --no-cov

test-exporters:
	$(PYTEST) tests/unit/exporters/ -v --no-cov

demo-happy:
	$(CLI) export examples/demo/Uber_Data.csv --outdir dist/demo

demo-issues:
	$(CLI) export examples/demo/issue_showcase/issue_demo.csv --outdir dist/issue_showcase

compare-demo:
	$(CLI) export examples/demo/Uber_Data.csv --outdir dist/demo
	$(CLI) export examples/demo/Uber_Data.csv --outdir dist/demo
	$(CLI) compare examples/demo/Uber_Data.csv --outdir dist/demo

clean:
	@echo Cleaning generated artifacts...
	-@powershell -NoProfile -Command "if (Test-Path dist) { Remove-Item -Recurse -Force dist }"
	-@powershell -NoProfile -Command "if (Test-Path htmlcov) { Remove-Item -Recurse -Force htmlcov }"
	-@powershell -NoProfile -Command "if (Test-Path .pytest_cache) { Remove-Item -Recurse -Force .pytest_cache }"
	-@powershell -NoProfile -Command "if (Test-Path .mypy_cache) { Remove-Item -Recurse -Force .mypy_cache }"
	-@powershell -NoProfile -Command "if (Test-Path .ruff_cache) { Remove-Item -Recurse -Force .ruff_cache }"
	-@powershell -NoProfile -Command "Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
	-@powershell -NoProfile -Command "Get-ChildItem -Recurse -Include *.pyc,*.pyo -File | Remove-Item -Force -ErrorAction SilentlyContinue"
