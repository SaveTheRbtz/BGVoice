"""Convert extracted domain models into storage records."""

from collections.abc import Iterable, Mapping, Sequence

from pydantic import BaseModel

from bgvoice.character_models import (
    CharacterDetail,
    CharacterExtraction,
    CharacterSound,
)
from bgvoice.dialogue_models import (
    DialogueExtraction,
    DialogueLine,
    DialogueTransitionEdge,
)
from bgvoice.model_types import (
    CreResource,
    DetailStatus,
    DlgResource,
    ExtractionState,
    ResourceSource,
    compose_search_text,
)
from bgvoice.storage_records import (
    CharacterData,
    CharacterRecord,
    CharacterSoundRecord,
    DialogueData,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    KeyedRecord,
)


def pending_character(
    resource: CreResource,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=resource.search_text,
    )


def retained_character(
    character: CharacterRecord,
    resource: CreResource,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=character.extraction,
        detail=character.detail,
        serialized_size=character.serialized_size,
        search_text=_character_search_text(resource.search_text, character.detail),
    )


def pending_character_refresh(
    character: CharacterRecord,
    run_id: str,
    timestamp: str,
) -> CharacterRecord:
    return _reset_character(
        character,
        _extraction_state(run_id, DetailStatus.PENDING, timestamp),
    )


def character_batch_records(
    run_id: str,
    timestamp: str,
    characters: Mapping[str, CharacterRecord],
    extractions: Sequence[CharacterExtraction],
    failures: Sequence[tuple[str, str]],
) -> tuple[list[CharacterRecord], list[CharacterSoundRecord]]:
    """Build the parent and sound rows for one completed CRE batch."""
    updates: list[CharacterRecord] = []
    sounds: list[CharacterSoundRecord] = []
    for extraction in extractions:
        character = characters[extraction.resource_name.casefold()]
        detail = CharacterData.model_validate(extraction.detail, from_attributes=True)
        updates.append(
            CharacterRecord(
                resource_name=character.resource_name,
                resref=character.resref,
                source=character.source,
                extraction=_extraction_state(run_id, DetailStatus.COMPLETE, timestamp),
                detail=detail,
                serialized_size=extraction.serialized_size,
                search_text=_character_search_text(_resource_search_text(character), detail),
            )
        )
        sounds.extend(
            _character_sound_record(run_id, character, extraction.detail, sound)
            for sound in extraction.sounds
        )
    for name, error in failures:
        updates.append(
            _reset_character(
                characters[name.casefold()],
                _extraction_state(run_id, DetailStatus.FAILED, timestamp, error[:2000]),
            )
        )
    return updates, sounds


def pending_dialogue(
    resource: DlgResource,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=_extraction_state(run_id, DetailStatus.PENDING, timestamp),
        detail=None,
        serialized_size=None,
        search_text=resource.search_text,
    )


def retained_dialogue(
    dialogue: DialogueRecord,
    resource: DlgResource,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=resource.resource_name,
        resref=resource.resref,
        source=ResourceSource.from_resource(resource),
        extraction=dialogue.extraction,
        detail=dialogue.detail,
        serialized_size=dialogue.serialized_size,
        search_text=resource.search_text,
    )


def pending_dialogue_refresh(
    dialogue: DialogueRecord,
    run_id: str,
    timestamp: str,
) -> DialogueRecord:
    return _reset_dialogue(
        dialogue,
        _extraction_state(run_id, DetailStatus.PENDING, timestamp),
    )


def dialogue_batch_records(
    run_id: str,
    timestamp: str,
    dialogues: Mapping[str, DialogueRecord],
    extractions: Sequence[DialogueExtraction],
    failures: Sequence[tuple[str, str]],
) -> tuple[list[DialogueRecord], list[DialogueLineRecord], list[DialogueTransitionRecord]]:
    """Build the parent, line, and transition rows for one completed DLG batch."""
    updates: list[DialogueRecord] = []
    lines: list[DialogueLineRecord] = []
    transitions: list[DialogueTransitionRecord] = []
    for extraction in extractions:
        dialogue = dialogues[extraction.resource_name.casefold()]
        updates.append(
            DialogueRecord(
                resource_name=dialogue.resource_name,
                resref=dialogue.resref,
                source=dialogue.source,
                extraction=_extraction_state(run_id, DetailStatus.COMPLETE, timestamp),
                detail=DialogueData.model_validate(extraction.detail, from_attributes=True),
                serialized_size=extraction.serialized_size,
                search_text=dialogue.search_text,
            )
        )
        lines.extend(_dialogue_line_record(run_id, dialogue, line) for line in extraction.lines)
        transitions.extend(
            _dialogue_transition_record(run_id, dialogue, edge) for edge in extraction.edges
        )
    for name, error in failures:
        updates.append(
            _reset_dialogue(
                dialogues[name.casefold()],
                _extraction_state(run_id, DetailStatus.FAILED, timestamp, error[:2000]),
            )
        )
    return updates, lines, transitions


def metadata_records[Record: KeyedRecord](
    record_type: type[Record],
    rows: Iterable[BaseModel],
) -> list[Record]:
    """Project typed metadata models into their matching Lance records."""
    return [record_type.model_validate(row, from_attributes=True) for row in rows]


def same_identity(
    record: CharacterRecord | DialogueRecord,
    resource: CreResource | DlgResource,
) -> bool:
    """Return whether an inventory resource still names the same effective source."""
    return (
        record.resource_name == resource.resource_name
        and record.resref.casefold() == resource.resref.casefold()
        and record.source.kind == resource.source_kind
        and record.source.path == resource.source_path
    )


def _reset_character(
    character: CharacterRecord,
    extraction: ExtractionState,
) -> CharacterRecord:
    return CharacterRecord(
        resource_name=character.resource_name,
        resref=character.resref,
        source=character.source,
        extraction=extraction,
        detail=None,
        serialized_size=None,
        search_text=_resource_search_text(character),
    )


def _reset_dialogue(
    dialogue: DialogueRecord,
    extraction: ExtractionState,
) -> DialogueRecord:
    return DialogueRecord(
        resource_name=dialogue.resource_name,
        resref=dialogue.resref,
        source=dialogue.source,
        extraction=extraction,
        detail=None,
        serialized_size=None,
        search_text=dialogue.search_text,
    )


def _dialogue_line_record(
    run_id: str,
    dialogue: DialogueRecord,
    line: DialogueLine,
) -> DialogueLineRecord:
    canonical = line.model_copy(update={"dialogue_resource_name": dialogue.resource_name})
    return DialogueLineRecord.model_validate(
        canonical.model_dump()
        | {
            "id": canonical.id,
            "run_id": run_id,
            "serialized_size": len(canonical.model_dump_json().encode("utf-8")),
            "search_text": canonical.search_text,
        }
    )


def _character_sound_record(
    run_id: str,
    character: CharacterRecord,
    detail: CharacterDetail,
    sound: CharacterSound,
) -> CharacterSoundRecord:
    return CharacterSoundRecord(
        id=CharacterSound.id_for(character.resource_name, sound.slot_id),
        run_id=run_id,
        character_resource_name=character.resource_name,
        slot_id=sound.slot_id,
        strref=sound.strref,
        text=sound.text,
        serialized_size=len(sound.model_dump_json().encode("utf-8")),
        search_text=compose_search_text(
            character.resource_name,
            character.resref,
            detail.display_name,
            str(sound.slot_id),
            str(sound.strref),
            sound.text,
        ),
    )


def _dialogue_transition_record(
    run_id: str,
    dialogue: DialogueRecord,
    edge: DialogueTransitionEdge,
) -> DialogueTransitionRecord:
    canonical = edge.model_copy(update={"dialogue_resource_name": dialogue.resource_name})
    return DialogueTransitionRecord.model_validate(
        canonical.model_dump()
        | {
            "id": canonical.id,
            "run_id": run_id,
            "serialized_size": len(canonical.model_dump_json().encode("utf-8")),
            "search_text": canonical.search_text,
        }
    )


def _extraction_state(
    run_id: str,
    status: DetailStatus,
    timestamp: str,
    error: str | None = None,
) -> ExtractionState:
    return ExtractionState(
        run_id=run_id,
        status=status,
        error=error,
        updated_at=timestamp,
    )


def _resource_search_text(record: CharacterRecord | DialogueRecord) -> str:
    return compose_search_text(
        record.resource_name,
        record.resref,
        record.source.path,
    )


def _character_search_text(
    resource_search_text: str,
    detail: CharacterData | None,
) -> str:
    if detail is None:
        return resource_search_text
    return compose_search_text(
        resource_search_text,
        detail.display_name,
        detail.short_name,
        detail.long_name,
        detail.death_variable,
        detail.dialog_resref,
        detail.override_script,
        detail.class_script,
        detail.race_script,
        detail.general_script,
        detail.default_script,
    )
