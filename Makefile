.PHONY: help install install-dev test lint format format-check type-check clean build release

help:
	@echo "Available targets:"
	@echo "  install      - Install the package"
	@echo "  install-dev  - Install the package with development dependencies"
	@echo "  test         - Run tests"
	@echo "  lint         - Run linting (flake8, pylint)"
	@echo "  format       - Format code (black, isort)"
	@echo "  format-check - Run format checking (black, isort with --check)"
	@echo "  type-check   - Run type checking (mypy)"
	@echo "  clean        - Clean build artifacts"
	@echo "  build        - Build the package"
	@echo "  release      - Build and check the package for release"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev,test]"

test:
	pytest

lint:
	flake8 src test
	pylint $(shell git ls-files '*.py')  # recommended invocation by GitHub Pylint template

format:
	black src test
	isort src test

format-check:
	black --check src test
	isort --check src test

type-check:
	mypy src

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -f coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build:
	python -m pip install build
	python -m build

release: clean build
	python -m pip install twine
	python -m twine check dist/*
	@echo "Package is ready for release. Run 'python -m twine upload dist/*' to publish."
