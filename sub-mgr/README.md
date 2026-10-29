# SubMgr

## Requirements

[uv](https://docs.astral.sh/uv/) is required.

```sh
uv sync
```

## Usage

Run from the `sub-mgr` directory:

```sh
uv run sub-mgr convert
uv run sub-mgr install
```

The equivalent module entry point is `uv run python -m sub_mgr <command>`.

Both `convert` and `install` process all enabled subscriptions by default.
Use `install --name NAME` (or `install -n NAME`) to install a single subscription.

To convert multiple subscriptions concurrently:

```sh
uv run sub-mgr convert --jobs 4
uv run sub-mgr convert -j 4
```

`--jobs` accepts a positive integer and defaults to `1` for sequential processing.
Each task converts one subscription and restores its proxies before completing.
The sequential mode keeps the two-second pause between tasks; concurrent mode omits that pause.
Logs are buffered separately for each task and printed together as soon as that task finishes, without waiting for the others.
The final summary follows configuration order and reports successful, failed, and skipped subscriptions.
Subscriptions must use distinct resolved output paths; duplicates are rejected before conversion starts.

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

