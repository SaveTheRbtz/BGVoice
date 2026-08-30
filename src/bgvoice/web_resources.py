"""Projection of typed read models into protobuf resources."""

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Final, cast

from lancedb.expr import col, lit

from bgvoice.model_types import (
    BIOGRAPHY_SOUND_SLOT_ID,
    AttributionPublicationStatus,
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    ReadableItemKind,
    RunKind,
    RunStatus,
    SourceKind,
)
from bgvoice.reader import PipelineReader
from bgvoice.reader_metadata import LabelResolver
from bgvoice.reader_models import (
    CharacterRow,
    ClassRow,
    DialogueLineRow,
    DialogueRow,
    DirectedLineRow,
    IdentifierRow,
    KitRow,
    RaceRow,
    ReadableItemRow,
    SoundRow,
    TransitionRow,
    VoiceRow,
)
from bgvoice.reader_views import character_row, dialogue_row
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
    DialogueRecord,
    ExtractionRunRecord,
)
from bgvoice.v1 import pipeline_pb2 as pb
from bgvoice.web_contract import INSTALLATION_ID, Collection, resource_name

_SOURCE_KIND: Final[dict[SourceKind, pb.SourceKind]] = {
    SourceKind.OVERRIDE: pb.SOURCE_KIND_OVERRIDE,
    SourceKind.BIF: pb.SOURCE_KIND_BIF,
    SourceKind.DLC: pb.SOURCE_KIND_DLC,
}
_DETAIL_STATUS: Final[dict[DetailStatus, pb.DetailStatus]] = {
    DetailStatus.PENDING: pb.DETAIL_STATUS_PENDING,
    DetailStatus.COMPLETE: pb.DETAIL_STATUS_COMPLETE,
    DetailStatus.FAILED: pb.DETAIL_STATUS_FAILED,
}
_ATTRIBUTION_STATUS: Final[dict[AttributionStatus, pb.AttributionStatus]] = {
    AttributionStatus.MATCHED: pb.ATTRIBUTION_STATUS_MATCHED,
    AttributionStatus.PARTIAL_MATCH: pb.ATTRIBUTION_STATUS_PARTIAL_MATCH,
    AttributionStatus.MISSING_DIALOGUE: pb.ATTRIBUTION_STATUS_MISSING_DIALOGUE,
    AttributionStatus.NO_DIALOGUE: pb.ATTRIBUTION_STATUS_NO_DIALOGUE,
    AttributionStatus.CHARACTER_UNAVAILABLE: pb.ATTRIBUTION_STATUS_CHARACTER_UNAVAILABLE,
}
_ATTRIBUTION_PUBLICATION: Final[
    dict[AttributionPublicationStatus, pb.AttributionPublicationStatus]
] = {
    AttributionPublicationStatus.MISSING: pb.ATTRIBUTION_PUBLICATION_STATUS_MISSING,
    AttributionPublicationStatus.STALE: pb.ATTRIBUTION_PUBLICATION_STATUS_STALE,
    AttributionPublicationStatus.PUBLISHED: pb.ATTRIBUTION_PUBLICATION_STATUS_PUBLISHED,
}
_LINE_KIND: Final[dict[DialogueLineKind, pb.DialogueLineKind]] = {
    DialogueLineKind.NPC: pb.DIALOGUE_LINE_KIND_NPC,
    DialogueLineKind.PLAYER: pb.DIALOGUE_LINE_KIND_PLAYER,
    DialogueLineKind.JOURNAL: pb.DIALOGUE_LINE_KIND_JOURNAL,
}
_IDENTIFIER_KIND: Final[dict[IdentifierKind, pb.IdentifierKind]] = {
    IdentifierKind.RACE: pb.IDENTIFIER_KIND_RACE,
    IdentifierKind.CLASS: pb.IDENTIFIER_KIND_CLASS,
    IdentifierKind.GENDER: pb.IDENTIFIER_KIND_GENDER,
    IdentifierKind.ALIGNMENT: pb.IDENTIFIER_KIND_ALIGNMENT,
    IdentifierKind.ENEMY_ALLY: pb.IDENTIFIER_KIND_ENEMY_ALLY,
    IdentifierKind.GENERAL: pb.IDENTIFIER_KIND_GENERAL,
    IdentifierKind.SPECIFIC: pb.IDENTIFIER_KIND_SPECIFIC,
    IdentifierKind.ANIMATION: pb.IDENTIFIER_KIND_ANIMATION,
    IdentifierKind.KIT: pb.IDENTIFIER_KIND_KIT,
    IdentifierKind.SOUND_SLOT: pb.IDENTIFIER_KIND_SOUND_SLOT,
}
_READABLE_ITEM_KIND: Final[dict[ReadableItemKind, pb.ReadableItemKind]] = {
    ReadableItemKind.BOOK: pb.READABLE_ITEM_KIND_BOOK,
    ReadableItemKind.SCROLL: pb.READABLE_ITEM_KIND_SCROLL,
}
_RUN_KIND: Final[dict[RunKind, pb.RunKind]] = {
    RunKind.CHARACTERS: pb.RUN_KIND_CHARACTERS,
    RunKind.DIALOGUES: pb.RUN_KIND_DIALOGUES,
    RunKind.PORTRAITS: pb.RUN_KIND_PORTRAITS,
    RunKind.READABLE_ITEMS: pb.RUN_KIND_READABLE_ITEMS,
    RunKind.METADATA: pb.RUN_KIND_METADATA,
    RunKind.ATTRIBUTION: pb.RUN_KIND_ATTRIBUTION,
}
_RUN_STATUS: Final[dict[RunStatus, pb.RunStatus]] = {
    RunStatus.RUNNING: pb.RUN_STATUS_RUNNING,
    RunStatus.COMPLETE: pb.RUN_STATUS_COMPLETE,
    RunStatus.COMPLETE_WITH_ERRORS: pb.RUN_STATUS_COMPLETE_WITH_ERRORS,
    RunStatus.FAILED: pb.RUN_STATUS_FAILED,
}


def attribution_publication(
    status: AttributionPublicationStatus,
) -> pb.AttributionPublicationStatus:
    return _ATTRIBUTION_PUBLICATION[status]


def source(kind: SourceKind, path: str) -> pb.ResourceSource:
    return pb.ResourceSource(kind=_SOURCE_KIND[kind], path=path)


def extraction(record: CharacterRecord | DialogueRecord) -> pb.ExtractionState:
    state = pb.ExtractionState(
        status=_DETAIL_STATUS[record.extraction.status],
        updated_at=timestamp(record.extraction.updated_at),
        extraction_run=resource_name(Collection.EXTRACTION_RUNS, record.extraction.run_id),
    )
    if record.extraction.error is not None:
        state.error = record.extraction.error
    return state


def dialogue_summary(row: CharacterRow) -> pb.CharacterDialogueSummary:
    return pb.CharacterDialogueSummary(
        declared_dialogue_count=row.declared_dialogue_count or 0,
        resolved_dialogue_count=row.resolved_dialogue_count or 0,
        dialogue_line_count=row.dialogue_line_count or 0,
        npc_line_count=row.npc_line_count or 0,
        player_line_count=row.player_line_count or 0,
        journal_line_count=row.journal_line_count or 0,
        state_count=row.dialogue_state_count or 0,
        transition_count=row.dialogue_transition_count or 0,
        serialized_size=row.dialogue_serialized_size or 0,
    )


def optional_value[T](values: Mapping[str, T], key: str) -> T | None:
    if key not in values:
        return None
    return values[key]


def voice(
    row: VoiceRow,
    characters: Mapping[str, CharacterRecord],
    portrait_resrefs: frozenset[str],
    attributions: Mapping[str, CharacterAttributionRecord],
    dialogues: Mapping[str, DialogueRecord],
    biography_sound_id: str | None = None,
) -> pb.Voice:
    dialogues_by_resref = {dialogue.resref.casefold(): dialogue for dialogue in dialogues.values()}
    npc_lines_by_dialogue = {
        name: 0 if dialogue.detail is None else dialogue.detail.npc_line_count
        for name, dialogue in dialogues.items()
    }
    message = pb.Voice(
        name=resource_name(Collection.VOICES, row.id),
        voice_id=row.id,
        display_name=row.display_name,
        prompt=row.prompt,
        npc_line_count=row.npc_line_count,
        serialized_size=row.serialized_size,
        directed_line_count=row.directed_line_count,
        generated_audio_count=row.generated_audio_count,
    )
    if row.generated_voice is not None:
        generated = row.generated_voice
        message.generated_voice.CopyFrom(
            pb.GeneratedVoice(
                description=generated.description,
                language_code=generated.language_code,
                inworld_voice_id=generated.inworld_voice_id,
                created_at=timestamp(generated.created_at),
            )
        )

    for name in row.variant_resource_names:
        dialogue_names = attributions[name.casefold()].resolved_dialogue_resource_names
        npc_lines = sum(
            npc_lines_by_dialogue[dialogue_name.casefold()]
            for dialogue_name in dialogue_names
            if dialogue_name.casefold() in npc_lines_by_dialogue
        )
        message.characters.add(
            name=resource_name(Collection.CHARACTERS, name),
            engine_resource_name=name,
            npc_line_count=npc_lines,
        )

    for resref in row.dialogue_resrefs:
        resource = f"{resref}.DLG"
        dialogue_record = dialogues_by_resref[resref.casefold()]
        message.dialogues.add(
            name=resource_name(Collection.DIALOGUES, resource),
            engine_resource_name=resource,
            npc_line_count=npc_lines_by_dialogue[dialogue_record.resource_name.casefold()],
        )

    for character_name in row.variant_resource_names:
        portrait = portrait_resref(characters[character_name])
        if portrait is not None and portrait.casefold() in portrait_resrefs:
            message.portrait = resource_name(Collection.PORTRAITS, portrait)
            break
    if biography_sound_id is not None:
        message.biography = resource_name(Collection.CHARACTER_SOUNDS, biography_sound_id)
    return message


def character_detail(row: CharacterRow, record: CharacterRecord) -> pb.CharacterDetail | None:
    detail = record.detail
    if detail is None:
        return None
    message = pb.CharacterDetail(
        short_name_strref=detail.short_name_strref,
        long_name_strref=detail.long_name_strref,
        gender_id=detail.gender_id,
        gender_label=_label(row.gender_label, detail.gender_id),
        race_id=detail.race_id,
        race_label=_label(row.race_label, detail.race_id),
        race=resource_name(Collection.RACES, str(detail.race_id)),
        class_id=detail.class_id,
        class_label=_label(row.class_label, detail.class_id),
        character_class=resource_name(Collection.CHARACTER_CLASSES, str(detail.class_id)),
        alignment_id=detail.alignment_id,
        alignment_label=_label(row.alignment_label, detail.alignment_id),
        enemy_ally_id=detail.enemy_ally_id,
        enemy_ally_label=_label(row.enemy_ally_label, detail.enemy_ally_id),
        general_id=detail.general_id,
        general_label=_label(row.general_label, detail.general_id),
        specific_id=detail.specific_id,
        specific_label=_label(row.specific_label, detail.specific_id),
        animation_id=detail.animation_id,
        animation_label=_label(row.animation_label, detail.animation_id),
        racial_enemy_id=detail.racial_enemy_id,
        racial_enemy_label=_label(row.racial_enemy_label, detail.racial_enemy_id),
        cre_kit_value=detail.cre_kit_value,
        class_levels=pb.CharacterClassLevels(
            first_class=detail.class_levels.first_class,
            second_class=detail.class_levels.second_class,
            third_class=detail.class_levels.third_class,
        ),
        base_attributes=pb.CharacterBaseAttributes(
            strength=detail.base_attributes.strength,
            strength_bonus=detail.base_attributes.strength_bonus,
            intelligence=detail.base_attributes.intelligence,
            wisdom=detail.base_attributes.wisdom,
            dexterity=detail.base_attributes.dexterity,
            constitution=detail.base_attributes.constitution,
            charisma=detail.base_attributes.charisma,
        ),
        morale=detail.morale,
        morale_break=detail.morale_break,
        morale_recovery_time=detail.morale_recovery_time,
        reputation=detail.reputation,
        cre_version=detail.cre_version,
    )
    for field_name in (
        "short_name",
        "long_name",
        "death_variable",
        "dialog_resref",
        "override_script",
        "class_script",
        "race_script",
        "general_script",
        "default_script",
    ):
        value = getattr(detail, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if detail.kit_ids_value is not None:
        message.kit_ids_value = detail.kit_ids_value
    if row.kit_label is not None:
        message.kit_label = row.kit_label
    if detail.small_portrait is not None:
        message.small_portrait_resref = detail.small_portrait
    if detail.large_portrait is not None:
        message.large_portrait_resref = detail.large_portrait
    return message


def _label(value: str | None, identifier: int) -> str:
    return value or str(identifier)


def portrait_resref(record: CharacterRecord) -> str | None:
    if record.detail is None:
        return None
    return record.detail.large_portrait or record.detail.small_portrait


def character(
    row: CharacterRow,
    record: CharacterRecord,
    portrait_resrefs: frozenset[str],
    biography_sound_id: str | None,
) -> pb.Character:
    message = pb.Character(
        name=resource_name(Collection.CHARACTERS, row.resource_name),
        engine_resource_name=row.resource_name,
        resref=row.resref,
        display_name=row.display_name or row.resref,
        source=source(record.source.kind, record.source.path),
        extraction=extraction(record),
        dialogue=dialogue_summary(row),
    )
    if row.voice_id is not None:
        message.voice = resource_name(Collection.VOICES, row.voice_id)
    if row.dialog_resref is not None and row.dialogue_status is DetailStatus.COMPLETE:
        message.direct_dialogue = resource_name(Collection.DIALOGUES, f"{row.dialog_resref}.DLG")
    portrait = portrait_resref(record)
    if portrait is not None and portrait.casefold() in portrait_resrefs:
        message.portrait = resource_name(Collection.PORTRAITS, portrait)
    if row.attribution_status is not None:
        message.attribution_status = _ATTRIBUTION_STATUS[row.attribution_status]
    if row.serialized_size is not None:
        message.serialized_size = row.serialized_size
    if biography_sound_id is not None:
        message.biography = resource_name(Collection.CHARACTER_SOUNDS, biography_sound_id)
    detail = character_detail(row, record)
    if detail is not None:
        message.detail.CopyFrom(detail)
    return message


def dialogue(row: DialogueRow, record: DialogueRecord) -> pb.Dialogue:
    message = pb.Dialogue(
        name=resource_name(Collection.DIALOGUES, row.resource_name),
        engine_resource_name=row.resource_name,
        resref=row.resref,
        source=source(record.source.kind, record.source.path),
        extraction=extraction(record),
        character_count=row.character_count,
        directed_line_count=row.directed_line_count,
        generated_audio_count=row.generated_audio_count,
    )
    if row.serialized_size is not None:
        message.serialized_size = row.serialized_size
    if record.detail is not None:
        detail = record.detail
        message.detail.CopyFrom(
            pb.DialogueDetail(
                dlg_version=detail.dlg_version,
                state_count=detail.state_count,
                transition_count=detail.transition_count,
                npc_line_count=detail.npc_line_count,
                player_line_count=detail.player_line_count,
                journal_line_count=detail.journal_line_count,
                dialogue_line_count=detail.dialogue_line_count,
            )
        )
    return message


def dialogue_line(row: DialogueLineRow) -> pb.DialogueLine:
    message = pb.DialogueLine(
        name=resource_name(Collection.DIALOGUE_LINES, row.id),
        dialogue=resource_name(Collection.DIALOGUES, row.dialogue_resource_name),
        dialogue_resref=row.dialogue_resref,
        source_kind=_SOURCE_KIND[row.source_kind],
        line_kind=_LINE_KIND[row.line_kind],
        state_index=row.state_index,
        strref=row.strref,
        tokens=row.tokens,
        serialized_size=row.serialized_size,
        character_count=row.character_count,
    )
    if row.state_trigger_index is not None:
        message.state_trigger_index = row.state_trigger_index
    if row.state_trigger_text is not None:
        message.state_trigger_text = row.state_trigger_text
    if row.transition_index is not None:
        message.transition_index = row.transition_index
    if row.text is not None:
        message.text = row.text
    message.directions.extend(map(directed_line, row.directions))
    return message


def directed_line(row: DirectedLineRow) -> pb.DirectedLine:
    message = pb.DirectedLine(
        id=row.id,
        voice=resource_name(Collection.VOICES, row.voice_id),
        voice_display_name=row.voice_display_name,
    )
    if row.character is not None:
        message.character.directed_dialogue = row.character.directed_dialogue
    else:
        assert row.narrator is not None
        message.narrator.directed_dialogue = row.narrator.directed_dialogue
    if row.audio_id is not None:
        message.audio_url = (
            f"/v1/installations/{INSTALLATION_ID}/generatedAudios/{row.audio_id}:download"
        )
    return message


def sound(row: SoundRow) -> pb.CharacterSound:
    message = pb.CharacterSound(
        name=resource_name(Collection.CHARACTER_SOUNDS, row.key),
        character=resource_name(Collection.CHARACTERS, row.character_resource_name),
        character_display_name=row.character_name,
        slot_id=row.slot_id,
        slot_symbols=row.slot_symbols,
        slot_groups=row.slot_groups,
        strref=row.strref,
        serialized_size=row.serialized_size,
    )
    if row.text is not None:
        message.text = row.text
    return message


def transition(row: TransitionRow) -> pb.DialogueTransition:
    message = pb.DialogueTransition(
        name=resource_name(Collection.DIALOGUE_TRANSITIONS, row.id),
        dialogue=resource_name(Collection.DIALOGUES, row.dialogue_resource_name),
        dialogue_resref=row.dialogue_resref,
        source_kind=_SOURCE_KIND[row.source_kind],
        state_index=row.state_index,
        transition_index=row.transition_index,
        flags_raw=row.flags_raw,
        flags_decoded=row.flags_decoded,
        terminates_dialogue=row.terminates_dialog,
        serialized_size=row.serialized_size,
    )
    for field_name in ("trigger_index", "trigger_text", "action_index", "action_text"):
        value = getattr(row, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if row.next_dialog is not None:
        message.next_dialogue_resref = row.next_dialog
        message.next_dialogue = resource_name(Collection.DIALOGUES, f"{row.next_dialog}.DLG")
    if row.next_state_index is not None:
        message.next_state_index = row.next_state_index
    return message


def race(rows: Sequence[RaceRow]) -> pb.Race:
    assert rows, "a race resource needs at least one source row"
    row = next((candidate for candidate in rows if candidate.name is not None), rows[0])
    symbols = _symbols(candidate.symbols for candidate in rows)
    message = pb.Race(
        name=resource_name(Collection.RACES, str(row.race_id)),
        race_id=row.race_id,
        symbols=symbols,
        display_name=row.name or _identifier_display(symbols, row.race_id),
    )
    message.texts.extend(filter(None, map(_race_text, rows)))
    return message


def _race_text(source: RaceRow) -> pb.RaceText | None:
    if source.source_resource is None:
        return None
    text = pb.RaceText(source_resource=source.source_resource, campaigns=source.campaigns)
    for field_name in (
        "row_name",
        "name_strref",
        "description_strref",
        "description",
        "uppercase_name_strref",
        "uppercase_name",
        "biography_strref",
        "biography",
    ):
        value = getattr(source, field_name)
        if value is not None:
            setattr(text, field_name, value)
    if source.name is not None:
        text.display_name = source.name
    return text


def character_class(rows: Sequence[ClassRow]) -> pb.CharacterClass:
    assert rows, "a class resource needs at least one source row"
    row = next(
        (
            candidate
            for candidate in rows
            if candidate.mixed_name is not None or candidate.lower_name is not None
        ),
        rows[0],
    )
    display_name = row.mixed_name or row.lower_name
    symbols = _symbols(candidate.symbols for candidate in rows)
    message = pb.CharacterClass(
        name=resource_name(Collection.CHARACTER_CLASSES, str(row.class_id)),
        class_id=row.class_id,
        symbols=symbols,
        display_name=display_name or _identifier_display(symbols, row.class_id),
    )
    message.texts.extend(filter(None, map(_character_class_text, rows)))
    return message


def _character_class_text(source: ClassRow) -> pb.CharacterClassText | None:
    if source.source_resource is None:
        return None
    text = pb.CharacterClassText(
        source_resource=source.source_resource,
        campaigns=source.campaigns,
    )
    for field_name in (
        "row_name",
        "class_text_kit_id",
        "lower_name_strref",
        "lower_name",
        "description_strref",
        "description",
        "mixed_name_strref",
        "mixed_name",
        "biography_strref",
        "biography",
        "fallen",
        "brief_description_strref",
        "brief_description",
        "fallen_notice_strref",
        "fallen_notice",
    ):
        value = getattr(source, field_name)
        if value is not None:
            setattr(text, field_name, value)
    return text


def _symbols(groups: Iterable[Sequence[str]]) -> list[str]:
    return list(dict.fromkeys(symbol for group in groups for symbol in group))


def _identifier_display(symbols: Sequence[str], identifier: int) -> str:
    return symbols[0] if symbols else str(identifier)


def kit(row: KitRow) -> pb.Kit:
    message = pb.Kit(
        name=resource_name(Collection.KITS, row.key),
        row_id=row.row_id,
        row_name=row.row_name,
        source_resource=row.source_resource,
        display_name=row.mixed_name or row.lower_name or row.row_name,
        class_symbols=row.class_symbols,
        kit_symbols=row.kit_symbols,
    )
    for field_name in (
        "lower_name",
        "mixed_name",
        "help_text",
        "kit_ids_value",
        "abilities_resref",
        "proficiency_column",
        "unusable_mask",
    ):
        value = getattr(row, field_name)
        if value is not None:
            setattr(message, field_name, value)
    if row.class_id is not None:
        message.character_class = resource_name(Collection.CHARACTER_CLASSES, str(row.class_id))
    return message


def identifier(row: IdentifierRow) -> pb.IdentifierDefinition:
    return pb.IdentifierDefinition(
        name=resource_name(Collection.IDENTIFIER_DEFINITIONS, row.key),
        kind=_IDENTIFIER_KIND[IdentifierKind(row.kind)],
        value=row.value,
        symbols=row.symbols,
        source_resource=row.source_resource,
        display_name=(row.symbols[0].replace("_", " ").title() if row.symbols else str(row.value)),
    )


def readable_item(row: ReadableItemRow) -> pb.ReadableItem:
    message = pb.ReadableItem(
        name=resource_name(Collection.READABLE_ITEMS, row.resource_name),
        engine_resource_name=row.resource_name,
        resref=row.resref,
        source=source(row.source.kind, row.source.path),
        kind=_READABLE_ITEM_KIND[row.kind],
        item_version=row.item_version,
        item_type=row.item_type,
        general_name=_tlk_string(row.general_name_strref, row.general_name),
        identified_name=_tlk_string(row.identified_name_strref, row.identified_name),
        general_description=_tlk_string(
            row.general_description_strref,
            row.general_description,
        ),
        identified_description=_tlk_string(
            row.identified_description_strref,
            row.identified_description,
        ),
        display_title=row.display_title,
        title_strref=row.title_strref,
        text=row.text,
        text_strref=row.text_strref,
        text_length=row.text_length,
        serialized_size=row.serialized_size,
    )
    for field_name in ("icon", "ground_icon", "description_image"):
        value = getattr(row, field_name)
        if value is not None:
            setattr(message, field_name, value)
    return message


def _tlk_string(strref: int, text: str | None) -> pb.TlkString:
    value = pb.TlkString(strref=strref)
    if text is not None:
        value.text = text
    return value


def extraction_run(row: ExtractionRunRecord) -> pb.ExtractionRun:
    message = pb.ExtractionRun(
        name=resource_name(Collection.EXTRACTION_RUNS, row.id),
        run_id=row.id,
        run_kind=_RUN_KIND[row.run_kind],
        started_at=timestamp(row.started_at),
        status=_RUN_STATUS[row.status],
        resources_discovered=row.resources_discovered,
        details_attempted=row.details_attempted,
        details_extracted=row.details_extracted,
        failures=row.failures,
        completed_at=(timestamp(row.completed_at) if row.completed_at is not None else None),
    )
    if row.error is not None:
        message.error = row.error
    return message


def timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert timestamp.tzinfo is not None, "pipeline timestamps must include a UTC offset"
    return timestamp


async def selected_characters(
    reader: PipelineReader,
    names: Sequence[str],
) -> dict[str, CharacterRecord]:
    if not names:
        return {}
    rows = cast(
        list[CharacterRecord],
        await reader.characters_table.query()
        .where(col("resource_name").isin(names))
        .to_pydantic(CharacterRecord),
    )
    return {row.resource_name: row for row in rows}


async def selected_dialogues(
    reader: PipelineReader,
    names: Sequence[str],
) -> dict[str, DialogueRecord]:
    if not names:
        return {}
    rows = cast(
        list[DialogueRecord],
        await reader.dialogues_table.query()
        .where(col("resource_name").isin(names))
        .to_pydantic(DialogueRecord),
    )
    return {row.resource_name: row for row in rows}


async def selected_dialogues_by_resref(
    reader: PipelineReader,
    resrefs: Sequence[str],
) -> list[DialogueRecord]:
    if not resrefs:
        return []
    return cast(
        list[DialogueRecord],
        await reader.dialogues_table.query()
        .where(col("resref").isin(resrefs))
        .to_pydantic(DialogueRecord),
    )


async def resolved_character_row(
    reader: PipelineReader,
    record: CharacterRecord,
) -> CharacterRow:
    metadata, attribution = await asyncio.gather(
        reader.metadata_snapshot(),
        reader.attribution_snapshot(),
    )
    key = record.resource_name.casefold()
    character_attribution = optional_value(attribution.by_character, key)
    voice = optional_value(attribution.voice_by_character, key)
    dialogue_names = (
        []
        if character_attribution is None
        else character_attribution.resolved_dialogue_resource_names
    )
    dialogues = await selected_dialogues(reader, dialogue_names)
    return character_row(
        record,
        character_attribution,
        voice,
        {name.casefold(): dialogue for name, dialogue in dialogues.items()},
        LabelResolver.from_snapshot(metadata),
    )


async def resolved_dialogue_row(
    reader: PipelineReader,
    record: DialogueRecord,
) -> DialogueRow:
    attribution = await reader.attribution_snapshot()
    generation = await reader.generation_snapshot(attribution)
    directed, audio = generation.dialogue_counts()
    key = record.resource_name.casefold()
    return dialogue_row(
        record,
        attribution.character_count_by_dialogue[key],
        directed[key],
        audio[key],
    )


async def load_portrait_resrefs(reader: PipelineReader) -> frozenset[str]:
    values = cast(
        list[str],
        (await reader.portrait_images_table.query().select(["resref"]).to_arrow())
        .column("resref")
        .to_pylist(),
    )
    return frozenset(value.casefold() for value in values)


async def biography_sounds(
    reader: PipelineReader,
    character_names: Sequence[str],
) -> dict[str, str]:
    if not character_names:
        return {}
    rows = (
        await reader.character_sounds_table.query()
        .where(
            (col("slot_id") == lit(BIOGRAPHY_SOUND_SLOT_ID))
            & col("character_resource_name").isin(character_names)
        )
        .select(["id", "character_resource_name"])
        .to_arrow()
    )
    ids = cast(list[str], rows.column("id").to_pylist())
    characters = cast(list[str], rows.column("character_resource_name").to_pylist())
    return dict(zip(characters, ids, strict=True))
