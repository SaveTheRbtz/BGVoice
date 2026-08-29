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

### Shared API generation

[`proto/bgvoice/v1/pipeline.proto`](proto/bgvoice/v1/pipeline.proto) is the single transport
contract. Buf generates Protobuf-ES models for React and standard Protobuf, type stubs, Connect,
and Python models from the same schema. The remote plugins are pinned in `buf.gen.yaml`; local
generation uses Buf 1.72.0:

```powershell
frontend/node_modules/.bin/buf lint
frontend/node_modules/.bin/buf generate
```

Generated files under `frontend/src/gen` and `src/bgvoice/v1` are committed and never edited by
hand. The authored pipeline models remain the source of truth for extraction and LanceDB storage;
the generated models own the service boundary shared by the Python backend and TypeScript UI.

### Code layout

- `model_types.py` owns shared engine and pipeline primitives; the character, dialogue, metadata,
  and pipeline model modules own their respective validated domain objects.
- `storage_records.py` and `storage_schema.py` define persistence. `database.py` writes extracted
  source data; `record_builders.py` projects it and `attribution.py` groups voices.
- `generation.py` orchestrates the iterative AI stages, `generation_ai.py` owns their tuned prompts
  and structured results, `generation_store.py` persists final outputs, and `inworld.py` is the
  small typed boundary for voice design and batch synthesis.
- `direction_audit.py` cheaply prefilters divergent direction/source pairs with RapidFuzz, then
  asks Luna for a structured semantic-equivalence decision without changing pipeline state.
- `mod_export.py` groups generated recordings by exact DLG text and emits the universal WeiDU
  content-intersection mod.
- `reader.py` coordinates read-only queries using focused query, metadata, view, statistics, and
  response-model modules. It does not depend on the writer repository.
- `web_service.py` implements the Connect contract; `web_query.py` owns request semantics and
  `web_resources.py` maps typed reader rows to transport resources.
- Frontend page modules own their API calls. Shared routing, filtering, browsing, and resource UI
  live in correspondingly named modules rather than an application-wide state facade.

Dependencies flow from domain models to storage, then to the repository/reader and API. The module
graph is intentionally acyclic.

## Pipeline

Run the stages in order:

```powershell
uv run bgvoice extract-metadata --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-dialogues --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-characters --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-portraits --game "D:\Games\BG\BG2EE-EET"
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
4. `extract-portraits` intersects the CRE portrait references with the effective BMP inventory,
   extracts every referenced image once, and stores its original dimensions and PNG bytes by resref.
5. `attribute-dialogues` combines direct CRE dialogue fields with imported party/banter links, then
   accounts for matched, dangling, and failed character references and every attributed or
   unattributed dialogue and line. It groups successfully extracted CREs by their resolved,
   case-insensitive display name and publishes only groups with NPC lines. Each voice retains its
   CRE membership and the distinct NPC-bearing DLGs attributed to any member, then receives a
   deterministic prompt from one real representative CRE's name, gender, race, class, optional
   non-trueclass kit, and alignment metadata. When member CREs provide `BIOGRAPHY_TEXT` in sound
   slot 74, the longest distinct biography is appended to the prompt and retained as a reference
   to its owning character sound. The browser resolves DLG metrics without copying them into the
   voice record.

Configure the two external services by copying `.env.example` to `.env`, then generate only the
missing outputs for one or more voices:

```powershell
uv run bgvoice generate --voice Imoen --voice Gorion --lines-per-voice 100
```

For each voice, dialogue resources are sorted once and their lowest remaining state is selected in
round-robin order. Voice design combines extracted metadata, ability scores, biography, and portrait
with required web research under an annotated 12-part voice profile. Dialogue direction has no web
access and returns an explicit character-or-narrator result for every line. Direction is submitted
one line per request with a stable prompt prefix. Its two-turn dialogue context is loaded once into
a typed in-memory index rather than queried line by line. Speech is ordered by provider
voice, packed into 200,000-character asynchronous Inworld jobs, and scheduled globally with at most
75 jobs and 15 million characters in flight: half of the Developer plan's published limits.
Inworld returns each batch line as one or more concatenated WAV segments. PyAV joins and normalizes
them into mono 22.05 kHz Ogg Vorbis at 90 kb/s. Published provider IDs, final voice descriptions,
directed text, game-ready audio bytes, and durable batch operation names are stored immediately.
Prompts, preview artifacts, manifests, and expiring signed URLs are not persisted. Re-running the
command resumes missing work.

The numeric `--lines-per-voice` value is a maximum, so shorter voices simply exhaust their available
lines. Use `--lines-per-voice all` to exhaust every non-empty NPC line attributed to each selected
voice. Existing voices, directions, and recordings are reused; only missing work is sent to the
external services.

Up to 75 voices are designed and directed concurrently. Line selection remains deterministic,
up to 100 single-line OpenAI direction requests may run concurrently, and generation state is
serialized at the database boundary. As soon as one voice's direction is complete, its missing
speech is scheduled under the shared Inworld limits while the other voices continue.

To deliberately replace selected character voices and all of their derived directions and audio,
use the recreation flag:

```powershell
uv run bgvoice generate --voice Imoen --voice Gorion --lines-per-voice 100 --recreate-voices
```

The command removes their corresponding tagged Inworld voices and regenerates the workload. The
shared narrator is reused; only the requested character voices are recreated.

Audit every stored direction against its extracted source text without modifying the database:

```powershell
uv run bgvoice audit-directions
```

The command removes engine templates and TTS hints only for comparison, sends pairs scoring below
80 (plus mechanically corrupted output) to Luna in ID-tagged batches, and writes confirmed
mismatches with their original and directed text to `data/direction-mismatches.json`. Use
`--similarity-threshold` or `--output` to override those defaults.

Package the game-ready recordings as one installable mod after generation completes:

```powershell
uv run python scripts/package_mod.py data/bgvoice-v1.0.0 data/BGVoice-v1.0.0.zip --version 1.0.0
```

The script exports the mod, parse-checks every generated WeiDU source, creates a root-clean Zip64
archive, verifies its CRCs, and prints its SHA-256. Release directories and archives are immutable:
choose new paths for each version. BGVoice replaces audio on every matched NPC dialogue occurrence.
Ogg Vorbis bytes remain in the Enhanced Edition's expected `.wav` resource files.

The mod is a content intersection rather than a snapshot patch. It opens every packaged DLG family
that exists in the target game, scans its current states, and matches the exact resolved English
text. DLG state numbers and TLK strrefs may differ; missing resources and unmatched text are simply
skipped. Repeated `(DLG, text)` pairs share one deterministic canonical recording.

Install BGVoice after all desired dialogue/content mods and preferably before `EET_end`. The
exporter reads EET's actual generated merge files and makes each final-dialogue catalog scan its
source JOIN dialogues too, so `EET_end` carries their sound-bearing TLK references into the merged
dialogue. The same mod can be installed directly on an already-finalized EET installation. If you
later change earlier mods, uninstall later components in reverse order and reinstall them in their
original order. Export while `EET_end` is installed so its generated dialogue-family map is present.

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
state in typed LanceDB tables with native full-text indexes. CRE and DLG rows own only their
resource envelope and nested extraction result; child lines, transitions, and sounds own their
intrinsic coordinates and content. Referenced portrait images are normalized to PNG and stored once
while characters retain their native portrait resrefs. Dialogue attribution and voice membership
are published as one run-scoped generation, with the completed run marker written last. Canonical
IDS values are normalized separately from campaign-specific race and class text, and duplicate IDS
aliases are preserved. Generated databases are local and reproducible, so schema changes are
handled by rebuilding from the EET installation rather than migrations. They are ignored because
they contain game text; see [`data/README.md`](data/README.md).

## Read-only browser

Build the frontend, then serve it with the API:

```powershell
cd frontend
pnpm build
cd ..
uv run bgvoice web
```

Open `http://127.0.0.1:8000`. The server exposes an async, read-only Connect API over committed
LanceDB table versions, so it can browse while extraction commits updates. The contract uses
canonical resource names, direct Get methods for routed details, cursor-based List methods, and
`order_by`. Its intentionally small filter grammar accepts `search(<JSON string>)` and unique
resource-specific `field = <JSON scalar>` clauses joined by uppercase ` AND `; malformed or
unknown clauses are invalid arguments. Request-bound cursors remain stable across local server
restarts, while UI routes remain separate, human-facing links. Voices are the first workspace and link to their characters,
dialogues, selected biography sounds, stored PNG portraits, generated voice descriptions, and
playable audio. Dialogue resources, lines,
transitions, CRE sounds, engine definitions, and extraction runs each have a focused routed view.

Native full-text indexes require no mirror tables or triggers. Search uses the English tokenizer
with stemming, 64-character tokens, case and ASCII folding, and retained stop words. Results
default to LanceDB's BM25 relevance; choosing a column explicitly overrides relevance. Characters
display resolved race, class, gender, alignment, allegiance, animation, and kit labels while
retaining their raw engine IDs.

## Quality checks

Ruff and ESLint enforce a cyclomatic-complexity ceiling of 15. The ceiling is a guardrail, not a
target: cohesive local code is preferred over one-use helpers created only to lower a score.

Tests follow the same principle. Small table-driven tests protect parsing and domain invariants;
one shared representative database covers read-only queries; mutation tests receive isolated
copies; and tests marked `integration` cross the pipeline, LanceDB, Connect, and HTTP boundaries.

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv build
frontend/node_modules/.bin/buf lint

cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm test:coverage
pnpm build
```

## Format references

- [LanceDB Python API](https://lancedb.github.io/lancedb/python/python/)
- [LanceDB full-text search](https://docs.lancedb.com/search/full-text-search)
- [Buf code generation](https://buf.build/docs/generate/)
- [Connect for Python](https://connectrpc.com/docs/python/getting-started/)
- [Connect for Web](https://connectrpc.com/docs/web/getting-started/)
- [Google API resource design](https://google.aip.dev/121)
- [Google API resource names](https://google.aip.dev/122)
- [Google API List methods](https://google.aip.dev/132)
- [Google API filtering](https://google.aip.dev/160)
- [`ie-cli`](https://github.com/emm-n-m/ie-cli), using
  [`v0.3.0-rc.1`](https://github.com/emm-n-m/ie-cli/releases/tag/v0.3.0-rc.1)
- [IESDP file format index](https://gibberlings3.github.io/iesdp/file_formats/index.htm)
- [WeiDU module and TP2 documentation](https://weidu.org/~thebigg/README-WeiDU.html)
- [EET installation order](https://github.com/Gibberlings3/EET/blob/master/EET/readme-EET.html)
- [EET modder's notes](https://github.com/Gibberlings3/EET/blob/master/EET/docs/Modder%27s%20Notes.html)
- [CRE V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm)
- [DLG V1](https://gibberlings3.github.io/iesdp/file_formats/ie_formats/dlg_v1.htm)
- [RACETEXT.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/racetext.htm)
- [CLASTEXT.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/clastext.htm)
- [KITLIST.2DA](https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/kitlist.htm)
