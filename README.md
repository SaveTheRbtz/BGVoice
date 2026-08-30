<p align="center">
  <img src="docs/assets/bgvoice-title-lockup.png" alt="BGVoice" width="720">
</p>

<p align="center">
  <strong>AI-generated voice-over for NPC dialogue in English Baldur's Gate: Enhanced Edition Trilogy.</strong>
</p>

BGVoice gives the Sword Coast a voice without tying the mod to one exact EET installation. Its
WeiDU installer finds compatible dialogue in the player's current mod setup and attaches the
packaged performances only where the speaker and English text match.

## Highlights

- Character-aware voices and context-aware delivery, including narration, whispers, pauses, and
  changes in emotion.
- Broad coverage of NPC conversations, quests, banter, and encounters across EET.
- Installation-time matching that tolerates different mod selections, dialogue layouts, state
  numbers, and TLK references.
- Conservative conflict handling: missing, changed, or ambiguous dialogue is left untouched.

> [!IMPORTANT]
> BGVoice replaces existing audio on every uniquely matched NPC dialogue line. It does not voice
> player responses, journal entries, books, or general combat and soundset lines.

## Requirements

- [Baldur's Gate: Enhanced Edition Trilogy](https://github.com/Gibberlings3/EET)
- The English game language (`en_US`)

Players need only a packaged BGVoice release. Python, API credentials, and the source pipeline are
required only to build a new voice catalog.

## Installation

1. Install EET and every dialogue or content mod you want to use.
2. Extract the complete BGVoice release into the EET game directory.
3. Run `setup-bgvoice.exe` and install BGVoice.
4. If the installation has not been finalized, run `EET_end` after BGVoice.

Recommended order:

```text
dialogue and content mods -> BGVoice -> EET_end
```

BGVoice can also be installed on an already-finalized EET setup.

## Updating or uninstalling

WeiDU manages backups and uninstallation. To update safely:

1. Uninstall components installed after BGVoice, then uninstall BGVoice.
2. Remove the old `bgvoice` folder, `setup-bgvoice.exe`, and `setup-bgvoice.tp2`.
3. Extract and install the new release.
4. Reinstall later components in their original order.

Do not extract a new release over the old `bgvoice` folder: obsolete catalogs could otherwise
remain installed.

## Compatibility

The installer discovers dialogue ownership from the target game, then matches the character name
and exact resolved English text. This makes recordings portable across EET versions and modsets
without depending on DLG names, state numbers, or TLK string references.

Resources absent from the target installation are skipped. Modified text is skipped. When a
dialogue occurrence has conflicting candidate voices, BGVoice leaves it unchanged instead of
guessing. The installer prints aggregate coverage totals when it finishes.

---

## Development

The rest of this repository builds the voice catalog and provides a read-only pipeline browser.

### Setup

Install [uv](https://docs.astral.sh/uv/) and pnpm, then run:

```powershell
uv sync
cd frontend
pnpm install
pnpm build
cd ..
```

`uv` installs Python 3.14 and manages `.venv`; activation is unnecessary. Put
[`ie-cli`](https://github.com/emm-n-m/ie-cli) v0.3.0-rc.1 at
`.tools/iecli/v0.3.0-rc.1/iecli.exe`, or pass `--iecli PATH` to extraction commands.

### Build the catalog

Run extraction against the effective EET installation, then publish dialogue attribution:

```powershell
uv run bgvoice extract-metadata --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-dialogues --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-characters --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-portraits --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice extract-readables --game "D:\Games\BG\BG2EE-EET"
uv run bgvoice attribute-dialogues
```

Copy `.env.example` to `.env`, then generate missing work. Existing voices, directions, audio, and
persisted provider jobs are reused by default.

```powershell
uv run bgvoice generate --voice Imoen --voice Gorion --lines-per-voice 100
uv run bgvoice audit-directions
```

Use `uv run bgvoice generate --help` for full-catalog generation, sparse shared profiles, or
deliberate voice recreation.

### Browse the pipeline

```powershell
cd frontend
pnpm build
cd ..
uv run bgvoice web
```

Open `http://127.0.0.1:8000`.

### Package a release

```powershell
uv run python scripts/package_mod.py `
  data/bgvoice-v1.3.0 `
  data/BGVoice-v1.3.0.zip `
  --version 1.3.0
```

The packager exports the WeiDU mod, parse-checks its sources, verifies the archive, and prints its
SHA-256 digest. Generated databases and releases stay under the ignored `data/` directory.

### Quality checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov=bgvoice --cov-report=term-missing:skip-covered
uv build

cd frontend
pnpm typecheck
pnpm lint
pnpm test:coverage
pnpm build
```

The Python pipeline uses typed Pydantic and LanceDB records. A single Protobuf contract at
[`proto/bgvoice/v1/pipeline.proto`](proto/bgvoice/v1/pipeline.proto) defines the Connect boundary
shared by the Python backend and React frontend.
