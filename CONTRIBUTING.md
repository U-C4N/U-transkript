# Contributing to U-Transkript

Thank you for your interest in contributing to U-Transkript! This guide will help you get started.

## Prerequisites

- **Python 3.10+** (check with `python --version`)
- **git** (check with `git --version`)
- A GitHub account

## Development Setup

1. **Fork and clone the repository:**

```bash
git clone https://github.com/<your-username>/u-transkript.git
cd u-transkript
```

2. **Create a virtual environment:**

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

3. **Install in development mode:**

```bash
pip install -e ".[dev]"
```

4. **Install pre-commit hooks:**

```bash
pip install pre-commit
pre-commit install
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=src --cov-report=term-missing

# Run a specific test file
pytest tests/unit/test_formatters.py

# Run tests matching a pattern
pytest -k "test_json"
```

We target 90%+ code coverage. Please include tests for any new functionality.

## Code Style

We use **ruff** for linting and formatting:

```bash
# Check for issues
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

Key conventions:
- Use type hints for all public function signatures
- Add `from __future__ import annotations` at the top of each module
- Use lowercase `dict`, `list`, `tuple` for type hints (Python 3.10+)
- Keep functions focused and under 50 lines where practical
- Write docstrings for all public classes and methods

## Pre-commit Hooks

Pre-commit hooks run automatically on `git commit`. They check:

- Code formatting (ruff)
- Linting (ruff)
- Type checking (mypy)
- Test execution (pytest)

If a hook fails, fix the issue and re-stage your changes before committing again.

To run hooks manually:

```bash
pre-commit run --all-files
```

## Making Changes

1. **Create a feature branch:**

```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes** following the code style guidelines above.

3. **Write tests** for any new functionality in the `tests/` directory.

4. **Run the test suite** to make sure nothing is broken:

```bash
pytest --cov=src
```

5. **Commit your changes:**

```bash
git add <files>
git commit -m "Add brief description of changes"
```

6. **Push and open a Pull Request:**

```bash
git push origin feature/your-feature-name
```

Then open a PR on GitHub against the `main` branch.

## Pull Request Guidelines

- Keep PRs focused on a single change or feature
- Write a clear title and description explaining what and why
- Reference any related issues (e.g., "Fixes #42")
- Ensure all CI checks pass before requesting review
- Respond to review feedback promptly

## Reporting Issues

When reporting a bug, please include:

1. **Python version** (`python --version`)
2. **Package version** (`pip show u-transkript`)
3. **Operating system** and version
4. **Steps to reproduce** the issue
5. **Expected behavior** vs. **actual behavior**
6. **Full error traceback** if applicable

For feature requests, describe:

1. **The problem** you are trying to solve
2. **Your proposed solution**
3. **Alternative approaches** you considered

## Project Structure

```
u-transkript/
  src/
    __init__.py          # Package metadata and exports
    youtube_transcript.py # Core YouTube API integration
    ai_translator.py     # Gemini AI translation
    transcript_list.py   # Transcript listing and selection
    fetched_transcript.py # Transcript fetching and parsing
    formatters.py        # Output formatters (SRT, VTT, JSON, etc.)
    exceptions.py        # Custom exception hierarchy
    utils/
      __init__.py        # Utils exports
      retry.py           # Retry decorator with backoff
      security.py        # URL validation and SSRF protection
      cache.py           # Disk-based transcript caching
      console.py         # Colored terminal output
  cli.py                 # Command-line interface
  tests/
    unit/                # Unit tests
    integration/         # Integration tests
    conftest.py          # Shared test fixtures
  docs/
    README.md            # User documentation
    example.md           # Usage examples
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
