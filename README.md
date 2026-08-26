# BGVoice

Python 3.14 tooling for extracting Baldur's Gate EET characters and dialogue, attributing lines,
and inspecting the result in a local web UI.

## Setup

Install [uv](https://docs.astral.sh/uv/) and pnpm, then run:

```powershell
uv sync
cd frontend
pnpm install
pnpm build
cd ..
```

`uv` selects Python 3.14 from `.python-version` and manages `.venv`; activation is unnecessary.
From the repository root, place `iecli.exe` at
`.tools/iecli/v0.3.0-rc.1/iecli.exe`, or pass `--iecli PATH` to extraction commands.

## Pipeline

Run the stages in order:

```powershell
uv run bgvoice extract-dialogues --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-characters --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice attribute-dialogues
```

1. `extract-dialogues` inventories every effective DLG and stores aggregate state and transition
   counts plus flattened NPC, player, and journal line records, not full state/transition objects.
2. `extract-characters` inventories every effective CRE and stores its voice-relevant metadata and
   dialogue reference.
3. `attribute-dialogues` accounts for matched and missing character references, characters without
   dialogue, and attributed and unattributed dialogues and lines.

Extraction defaults to the available logical CPU count, skips completed records, and accepts
`--refresh` to rebuild them. Character extraction also accepts `--inventory-only`.

The default database is `data/bgvoice.sqlite3`. Strict Pydantic projections validate `ie-cli`
output; SQLModel handles application persistence; SQLite supplies foreign keys, `STRICT` tables,
transactions, WAL, and FTS5 indexes. Generated databases are local and reproducible, so schema
changes are handled by rebuilding from the EET installation rather than migrations. They are also
ignored because they contain game text; see [`data/README.md`](data/README.md).

## Read-only browser

Build the frontend, then serve it with the API:

```powershell
cd frontend
pnpm build
cd ..
uv run bgvoice web
```

Open `http://127.0.0.1:8000`. The server uses short-lived read-only SQLite sessions with
`query_only` enabled. WAL allows browsing while extraction writes, and trigger-free FTS5 virtual
indexes are updated transactionally with writer batches so committed searches stay current. The
Characters, Dialogues, and Lines tabs provide search, filters, sorting, pagination, and line
coordinates.

## Quality checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build

cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

## Format references

- [`ie-cli`](https://github.com/emm-n-m/ie-cli), using
  [`v0.3.0-rc.1`](https://github.com/emm-n-m/ie-cli/releases/tag/v0.3.0-rc.1)
- [IESDP file format index](https://gibberlings3.github.io/iesdp/file_formats/index.htm)
- [CRE V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm)
- [DLG V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/dlg_v1.htm)
