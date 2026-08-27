"""Pipeline progress, run summaries, and attribution statistics."""

from pathlib import Path

from pydantic import Field

from bgvoice.model_types import StrictModel, TerminalRunStatus


class ExtractionProgress(StrictModel):
    """Progress event emitted while resource details are extracted."""

    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)


class ExtractionSummary(StrictModel):
    """Machine-readable terminal result of one extraction run."""

    run_id: str = Field(min_length=1)
    game_root: Path
    database_path: Path
    iecli_version: str
    discovered: int = Field(ge=0)
    attempted: int = Field(ge=0)
    extracted: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    status: TerminalRunStatus


class DatabaseStats(StrictModel):
    """Counts describing the active character inventory."""

    total: int = Field(ge=0)
    complete: int = Field(ge=0)
    failed: int = Field(ge=0)
    pending: int = Field(ge=0)
    with_dialog: int = Field(ge=0)


class AttributionSummary(StrictModel):
    """Complete accounting of active characters and extracted DLG resources."""

    run_id: str = Field(min_length=1)
    characters_total: int = Field(ge=0)
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_partially_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_attributed: int = Field(ge=0)
    dialogues_unattributed: int = Field(ge=0)
    attributed_dialogue_lines: int = Field(ge=0)
    unattributed_dialogue_lines: int = Field(ge=0)
