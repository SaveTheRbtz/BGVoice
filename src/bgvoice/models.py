"""Validated ``ie-cli`` projections and pipeline records.

Binary field semantics come from IESDP's CRE V1 and DLG V1 specifications:
https://gibberlings3.github.io/iesdp/file_formats/ie_formats/cre_v1.htm
https://gibberlings3.github.io/iesdp/file_formats/ie_formats/dlg_v1.htm
"""

import re
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DialogueLineKind(StrEnum):
    NPC = "npc"
    PLAYER = "player"
    JOURNAL = "journal"


class DetailStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class AttributionStatus(StrEnum):
    MATCHED = "matched"
    MISSING_DIALOGUE = "missing_dialogue"
    DIALOGUE_FAILED = "dialogue_failed"
    NO_DIALOGUE = "no_dialogue"
    CHARACTER_UNAVAILABLE = "character_unavailable"


class RunKind(StrEnum):
    CHARACTERS = "characters"
    DIALOGUES = "dialogues"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"
    FAILED = "failed"


type TerminalRunStatus = Literal[
    RunStatus.COMPLETE,
    RunStatus.COMPLETE_WITH_ERRORS,
    RunStatus.FAILED,
]


class SourceKind(StrEnum):
    OVERRIDE = "override"
    BIF = "bif"
    DLC = "dlc"


type ResRef = Annotated[str, Field(min_length=1, max_length=8)]
type UInt8 = Annotated[int, Field(ge=0, le=0xFF)]
type UInt32 = Annotated[int, Field(ge=0, le=0xFFFF_FFFF)]

_EE_COLOR_TAG = re.compile(r"\^(?:0x[0-9A-Fa-f]{8}|-)")


class StrictModel(BaseModel):
    """Base model that rejects implicit coercion and unknown fields."""

    model_config = ConfigDict(strict=True, extra="forbid")


class IeCliProjection(BaseModel):
    """Strictly validate fields used here while allowing unused upstream fields."""

    model_config = ConfigDict(strict=True, extra="ignore")


class CreResource(StrictModel):
    """One effective CRE resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["CRE"] = Field(alias="type")


class DlgResource(StrictModel):
    """One effective DLG resource returned by ``iecli list``."""

    resource_name: str = Field(min_length=1)
    resref: ResRef
    source_kind: SourceKind = Field(strict=False)
    source_path: str = Field(min_length=1)
    resource_type: Literal["DLG"] = Field(alias="type")


class StringReference(StrictModel):
    """A TLK string reference and its resolved text."""

    strref: UInt32
    text: str | None


class CreClassification(StrictModel):
    """CRE V1 bytes 0x270-0x27B, interpreted through the corresponding IDS tables."""

    enemy_ally: UInt8
    general: UInt8
    race: UInt8
    class_id: UInt8 = Field(alias="class")
    specific: UInt8
    gender: UInt8
    alignment: UInt8


class CreScripts(StrictModel):
    """CRE V1 script resrefs at 0x248-0x268, in file order."""

    override_script: ResRef | None
    class_script: ResRef | None
    race_script: ResRef | None
    general_script: ResRef | None
    default_script: ResRef | None


class CreHeader(IeCliProjection):
    """Voice-relevant CRE V1 header fields, named exactly as ``ie-cli`` emits them."""

    # CRE V1 0x008 is the long name; 0x00C is the short tooltip name.
    long_name: StringReference
    short_name: StringReference
    small_portrait: ResRef | None
    large_portrait: ResRef | None
    scripts: CreScripts
    classification: CreClassification
    death_variable: str
    dialog: ResRef | None


class CreDump(IeCliProjection):
    """Voice-relevant fields parsed from ``iecli dump`` JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["CRE"]
    version: Literal["V1.0"]
    header: CreHeader


class DlgTransition(IeCliProjection):
    """One DLG V1 transition: an optional player response and/or journal entry."""

    index: UInt32
    player_text: StringReference | None
    journal_text: StringReference | None


class DlgState(IeCliProjection):
    """One DLG V1 actor-response state and its outgoing player transitions."""

    index: UInt32
    response_text: StringReference
    transitions: list[DlgTransition]


class DlgHeader(IeCliProjection):
    """DLG V1 table counts reported by ``ie-cli`` from header offsets 0x008 and 0x010."""

    num_states: UInt32
    num_transitions: UInt32


class DlgDump(IeCliProjection):
    """Voice-relevant fields parsed from ``iecli dump`` DLG JSON."""

    resource_name: str = Field(min_length=1)
    resource_type: Literal["DLG"]
    version: Literal["V1.0"]
    header: DlgHeader
    states: list[DlgState]

    @model_validator(mode="after")
    def validate_header_counts(self) -> Self:
        """Reject a partial or internally inconsistent decoded DLG."""
        assert len(self.states) == self.header.num_states, (
            f"DLG header declares {self.header.num_states} states; decoded {len(self.states)}"
        )
        transition_count = sum(len(state.transitions) for state in self.states)
        assert transition_count == self.header.num_transitions, (
            f"DLG header declares {self.header.num_transitions} transitions; "
            f"decoded {transition_count}"
        )
        return self


class CharacterDetail(StrictModel):
    """Normalized, voice-relevant detail from one CRE resource."""

    resource_name: str
    display_name: str
    short_name: str | None
    short_name_strref: UInt32
    long_name: str | None
    long_name_strref: UInt32
    death_variable: str | None
    dialog_resref: str | None
    gender_id: UInt8
    race_id: UInt8
    class_id: UInt8
    alignment_id: UInt8
    enemy_ally_id: UInt8
    general_id: UInt8
    specific_id: UInt8
    override_script: str | None
    class_script: str | None
    race_script: str | None
    general_script: str | None
    default_script: str | None
    small_portrait: str | None
    large_portrait: str | None
    cre_version: str

    @classmethod
    def from_dump(cls, resource: CreResource, dump: CreDump) -> Self:
        """Project validated ie-cli data into the database model."""
        header = dump.header
        short_name = _optional_text(header.short_name.text)
        long_name = _optional_text(header.long_name.text)
        display_name = clean_display_name(short_name or long_name) or resource.resref
        classification = header.classification
        scripts = header.scripts
        return cls(
            resource_name=resource.resource_name,
            display_name=display_name,
            short_name=short_name,
            short_name_strref=header.short_name.strref,
            long_name=long_name,
            long_name_strref=header.long_name.strref,
            death_variable=_optional_text(header.death_variable),
            dialog_resref=_optional_resref(header.dialog),
            gender_id=classification.gender,
            race_id=classification.race,
            class_id=classification.class_id,
            alignment_id=classification.alignment,
            enemy_ally_id=classification.enemy_ally,
            general_id=classification.general,
            specific_id=classification.specific,
            override_script=_optional_resref(scripts.override_script),
            class_script=_optional_resref(scripts.class_script),
            race_script=_optional_resref(scripts.race_script),
            general_script=_optional_resref(scripts.general_script),
            default_script=_optional_resref(scripts.default_script),
            small_portrait=_optional_resref(header.small_portrait),
            large_portrait=_optional_resref(header.large_portrait),
            cre_version=dump.version,
        )


class DialogueDetail(StrictModel):
    """Normalized, sortable metrics for one DLG resource."""

    resource_name: str
    resref: str
    dlg_version: str
    state_count: UInt32
    transition_count: UInt32
    npc_line_count: int = Field(ge=0)
    player_line_count: int = Field(ge=0)
    journal_line_count: int = Field(ge=0)
    dialogue_line_count: int = Field(ge=0)
    pydantic_json_size: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        assert self.npc_line_count == self.state_count, (
            "DLG state count must equal its NPC line count"
        )
        assert self.dialogue_line_count == self.npc_line_count + self.player_line_count, (
            "DLG spoken line count must equal NPC plus player lines"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        """Count spoken and journal text while retaining header consistency."""
        player_lines = sum(
            transition.player_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        journal_lines = sum(
            transition.journal_text is not None
            for state in dump.states
            for transition in state.transitions
        )
        npc_lines = len(dump.states)
        return cls(
            resource_name=dump.resource_name,
            resref=dump.resource_name.removesuffix(".DLG"),
            dlg_version=dump.version,
            state_count=dump.header.num_states,
            transition_count=dump.header.num_transitions,
            npc_line_count=npc_lines,
            player_line_count=player_lines,
            journal_line_count=journal_lines,
            dialogue_line_count=npc_lines + player_lines,
            pydantic_json_size=len(dump.model_dump_json().encode("utf-8")),
        )


class DialogueLine(StrictModel):
    """One actor, player, or journal strref extracted from a validated DLG."""

    dialogue_resource_name: str
    line_kind: DialogueLineKind
    state_index: UInt32
    transition_index: UInt32 | None = None
    strref: UInt32
    text: str | None

    @classmethod
    def from_dump(cls, dump: DlgDump) -> list[Self]:
        """Flatten DLG states and transitions into stable line-level records."""
        lines: list[Self] = []
        for state in dump.states:
            lines.append(
                cls(
                    dialogue_resource_name=dump.resource_name,
                    line_kind=DialogueLineKind.NPC,
                    state_index=state.index,
                    transition_index=None,
                    strref=state.response_text.strref,
                    text=state.response_text.text,
                )
            )
            for transition in state.transitions:
                for kind, reference in (
                    (DialogueLineKind.PLAYER, transition.player_text),
                    (DialogueLineKind.JOURNAL, transition.journal_text),
                ):
                    if reference is not None:
                        lines.append(
                            cls(
                                dialogue_resource_name=dump.resource_name,
                                line_kind=kind,
                                state_index=state.index,
                                transition_index=transition.index,
                                strref=reference.strref,
                                text=reference.text,
                            )
                        )
        return lines


class DialogueExtraction(StrictModel):
    """One DLG's aggregate metrics and addressable line records."""

    detail: DialogueDetail
    lines: list[DialogueLine]

    @model_validator(mode="after")
    def validate_line_resources(self) -> Self:
        unexpected = sorted(
            {
                line.dialogue_resource_name
                for line in self.lines
                if line.dialogue_resource_name != self.detail.resource_name
            }
        )
        assert not unexpected, (
            f"DLG extraction {self.detail.resource_name!r} contains lines for {unexpected}"
        )
        counts = Counter(line.line_kind for line in self.lines)
        expected: dict[DialogueLineKind, int] = {
            DialogueLineKind.NPC: self.detail.npc_line_count,
            DialogueLineKind.PLAYER: self.detail.player_line_count,
            DialogueLineKind.JOURNAL: self.detail.journal_line_count,
        }
        assert all(counts[kind] == count for kind, count in expected.items()), (
            f"DLG extraction {self.detail.resource_name!r} line counts are "
            f"{dict(counts)}; expected {expected}"
        )
        return self

    @classmethod
    def from_dump(cls, dump: DlgDump) -> Self:
        return cls(detail=DialogueDetail.from_dump(dump), lines=DialogueLine.from_dump(dump))


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

    characters_total: int = Field(ge=0)
    characters_unavailable: int = Field(ge=0)
    characters_matched: int = Field(ge=0)
    characters_missing_dialogue: int = Field(ge=0)
    characters_dialogue_failed: int = Field(ge=0)
    characters_without_dialogue: int = Field(ge=0)
    dialogues_total: int = Field(ge=0)
    dialogues_attributed: int = Field(ge=0)
    dialogues_unattributed: int = Field(ge=0)
    attributed_dialogue_lines: int = Field(ge=0)
    unattributed_dialogue_lines: int = Field(ge=0)


def clean_display_name(value: str | None) -> str | None:
    """Remove Enhanced Edition color tags while preserving the original text elsewhere."""
    if value is None:
        return None
    cleaned = _EE_COLOR_TAG.sub("", value).strip()
    return cleaned or None


def utc_now() -> datetime:
    """Return an aware UTC timestamp for persisted extraction metadata."""
    return datetime.now(UTC)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_resref(value: str | None) -> str | None:
    stripped = _optional_text(value)
    if stripped is None or stripped.upper() == "NONE":
        return None
    return stripped
