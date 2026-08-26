# BGVoice

AI-generated voice-over tooling for Baldur's Gate Enhanced Edition Trilogy dialogue.

The project currently contains only its Python 3.14 development foundation. Domain code will
be added incrementally.

## Setup

Install [uv](https://docs.astral.sh/uv/), then run:

```powershell
uv sync
```

uv selects Python 3.14 from `.python-version` and creates an isolated `.venv` automatically.
You do not need to activate it when using `uv run`.

## Quality checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
```

To apply safe formatting and lint fixes while developing:

```powershell
uv run ruff format .
uv run ruff check --fix .
```
