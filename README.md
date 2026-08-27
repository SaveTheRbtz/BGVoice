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
uv run bgvoice extract-metadata --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-dialogues --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-characters --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice attribute-dialogues
```

1. `extract-metadata` imports the effective IDS definitions; every campaign resource selected by
   `CAMPAIGN.2DA`; race, class, kit, and favored-enemy text; `SNDSLOT`, `SPEECH`, `CHARSND`, and
   `CSOUND` voice metadata; `HAPPY` voice-reaction and `BANTTIMG` banter controls;
   `INTERDIA`/`PDIALOG` character links; `INTERACT` rules; and `ENGINEST`, `MONTHS`, and campaign
   `YEARS` strings. TLK-backed rows retain both their strrefs and resolved English text.
2. `extract-dialogues` inventories every effective DLG and stores its states, flattened NPC,
   player, and journal lines, macro tokens, state triggers, and complete transition edges including
   conditions, actions, flags, and destinations.
3. `extract-characters` inventories every effective CRE and stores its voice-relevant metadata,
   populated soundset lines, dialogue reference, typed engine classifications, animation, class
   levels, abilities, morale, reputation, racial enemy, and both raw and normalized kit values.
4. `attribute-dialogues` combines direct CRE dialogue fields with imported party/banter links, then
   accounts for matched, dangling, and failed character references and every attributed or
   unattributed dialogue and line.

The effective EET `TOKENTXT.2DA` currently has no rows, so there is nothing useful to persist from
it. Runtime tokens found in DLG text are retained verbatim instead; the engine and calendar tables
provide the immediately resolvable static text behind common date macros.

`ie-cli` 0.3.0-rc.1 resolves TLK strrefs to text but does not expose the TLK sound resref, so the
current import cannot yet associate dialogue strings with existing WAV resources.

Extraction defaults to the available logical CPU count, skips completed records, and accepts
`--refresh` to rebuild them. Character extraction also accepts `--inventory-only`.

The default database is the `data/bgvoice.lancedb` directory. Strict Pydantic projections validate
the fields consumed from `ie-cli` output, while tolerating unrelated fields added by future
versions; typed LanceModel rows define the stored schema. The pipeline keeps its current
state in typed LanceDB tables with native full-text indexes. Canonical IDS values are normalized
separately from campaign-specific race and class text, and duplicate IDS aliases are preserved.
Generated
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
clicking a column explicitly overrides relevance. Characters display resolved race, class, gender,
alignment, allegiance, animation, and kit labels while retaining their raw IDs. Characters,
Dialogues, Lines, Voices, and Transitions have dedicated pipeline views; Races, Classes, Kits, and
Identifiers expose the imported engine metadata.

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
- [RACETEXT.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/racetext.htm)
- [CLASTEXT.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/clastext.htm)
- [KITLIST.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/kitlist.htm)
