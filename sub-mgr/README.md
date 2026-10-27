# SubMgr

## Requirements

[uv](https://docs.astral.sh/uv/) is required.

```sh
uv sync
```

## Usage

```sh
uv run ./main.py convert
uv run ./main.py install
```

## Tests

Run from the `sub-mgr` directory:

```sh
uv run pytest tests -v
```

`uv run` installs development dependencies and runs pytest in the project virtual environment.
Tests use temporary files and mocked HTTP responses; they do not contact subscription services or modify local subscription settings.

## Pre-commit checks

```sh
uv run pre-commit install          # Install the Git hook once per local repository
uv run pre-commit run --all-files  # Check all tracked files
uv run pre-commit                  # Check staged files
```

The repository root `.pre-commit-config.yaml` runs separate checks for `sub-mgr` and `acme-cloudflare`.
Each project uses its own locked development dependencies for Ruff linting (including import sorting and automatic fixes), Ruff formatting, and pytest.
Tests run when Python files, `pyproject.toml`, or `uv.lock` change in that project.
If a hook modifies files, stage those changes and commit again.

