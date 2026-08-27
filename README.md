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

The default database is the `data/bgvoice.lancedb` directory. Strict Pydantic projections validate
`ie-cli` output, and typed LanceModel rows define the stored schema. The pipeline keeps its current
state in a small set of denormalized LanceDB tables with native full-text indexes. Generated
databases are local and reproducible, so schema changes are handled by rebuilding from the EET
installation rather than migrations. They are also ignored because they contain game text; see
[`data/README.md`](data/README.md).

## Read-only browser

Build the frontend, then serve it with the API:

```powershell
cd frontend
pnpm build
cd ..
uv run bgvoice web
```

Open `http://127.0.0.1:8000`. The server exposes a read-only API over committed LanceDB table
versions, so it can browse while extraction writes new snapshots. Native full-text indexes require
no mirror tables or triggers. Search uses the English tokenizer with stemming, 64-character tokens,
case and ASCII folding, and retained stop words. Results default to LanceDB's BM25 relevance;
clicking a column explicitly overrides relevance. The Characters, Dialogues, and Lines tabs also
provide filters, pagination, and line coordinates.

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

- [LanceDB Python API](https://lancedb.github.io/lancedb/python/python/)
- [LanceDB full-text search](https://docs.lancedb.com/search/full-text-search)
- [`ie-cli`](https://github.com/emm-n-m/ie-cli), using
  [`v0.3.0-rc.1`](https://github.com/emm-n-m/ie-cli/releases/tag/v0.3.0-rc.1)
- [IESDP file format index](https://gibberlings3.github.io/iesdp/file_formats/index.htm)
- [CRE V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm)
- [DLG V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/dlg_v1.htm)
