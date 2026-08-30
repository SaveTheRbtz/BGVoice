"""Projection from stored records to typed browser rows."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bgvoice.attribution import voice_representative
from bgvoice.model_types import (
    AttributionStatus,
    DetailStatus,
    IdentifierKind,
)
from bgvoice.reader_metadata import LabelResolver
from bgvoice.reader_models import (
    CharacterRow,
    DialogueLineRow,
    DialogueRow,
    DirectedLineRow,
    GeneratedVoiceRow,
    TransitionRow,
    VoiceRow,
)
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    VoiceResourceRecord,
)


@dataclass(frozen=True, slots=True)
class CharacterDialogueMetrics:
    attribution_status: AttributionStatus | None = None
    dialogue_status: DetailStatus | None = None
    declared_dialogue_count: int | None = None
    resolved_dialogue_count: int | None = None
    dialogue_line_count: int | None = None
    npc_line_count: int | None = None
    player_line_count: int | None = None
    journal_line_count: int | None = None
    dialogue_state_count: int | None = None
    dialogue_transition_count: int | None = None
    dialogue_serialized_size: int | None = None


def character_row(
    record: CharacterRecord,
    attribution: CharacterAttributionRecord | None,
    voice: VoiceResourceRecord | None,
    dialogues: Mapping[str, DialogueRecord],
    labels: LabelResolver,
) -> CharacterRow:
    detail = record.detail
    metrics = character_dialogue_metrics(attribution, dialogues)
    if detail is None:
        display_name = dialog_resref = None
        gender_id = race_id = class_id = None
        alignment_id = enemy_ally_id = general_id = None
        specific_id = animation_id = racial_enemy_id = None
        cre_kit_value = kit_ids_value = None
        first_class_level = second_class_level = third_class_level = None
    else:
        display_name = detail.display_name
        dialog_resref = detail.dialog_resref
        gender_id = detail.gender_id
        race_id = detail.race_id
        class_id = detail.class_id
        alignment_id = detail.alignment_id
        enemy_ally_id = detail.enemy_ally_id
        general_id = detail.general_id
        specific_id = detail.specific_id
        animation_id = detail.animation_id
        racial_enemy_id = detail.racial_enemy_id
        cre_kit_value = detail.cre_kit_value
        kit_ids_value = detail.kit_ids_value
        first_class_level = detail.class_levels.first_class
        second_class_level = detail.class_levels.second_class
        third_class_level = detail.class_levels.third_class

    return CharacterRow(
        resource_name=record.resource_name,
        display_name=display_name,
        voice_id=None if voice is None else voice.voice_id,
        resref=record.resref,
        source_kind=record.source.kind,
        dialog_resref=dialog_resref,
        gender_id=gender_id,
        race_id=race_id,
        class_id=class_id,
        alignment_id=alignment_id,
        enemy_ally_id=enemy_ally_id,
        general_id=general_id,
        specific_id=specific_id,
        animation_id=animation_id,
        racial_enemy_id=racial_enemy_id,
        cre_kit_value=cre_kit_value,
        kit_ids_value=kit_ids_value,
        first_class_level=first_class_level,
        second_class_level=second_class_level,
        third_class_level=third_class_level,
        detail_status=record.extraction.status,
        detail_error=record.extraction.error,
        attribution_status=metrics.attribution_status,
        serialized_size=record.serialized_size,
        dialogue_status=metrics.dialogue_status,
        declared_dialogue_count=metrics.declared_dialogue_count,
        resolved_dialogue_count=metrics.resolved_dialogue_count,
        dialogue_line_count=metrics.dialogue_line_count,
        npc_line_count=metrics.npc_line_count,
        player_line_count=metrics.player_line_count,
        journal_line_count=metrics.journal_line_count,
        dialogue_state_count=metrics.dialogue_state_count,
        dialogue_transition_count=metrics.dialogue_transition_count,
        dialogue_serialized_size=metrics.dialogue_serialized_size,
        updated_at=record.extraction.updated_at,
        **character_labels(record, labels),
    )


def character_labels(record: CharacterRecord, labels: LabelResolver) -> dict[str, str | None]:
    detail = record.detail
    if detail is None:
        return {
            field: None
            for field in (
                "gender_label",
                "race_label",
                "class_label",
                "alignment_label",
                "enemy_ally_label",
                "general_label",
                "specific_label",
                "animation_label",
                "racial_enemy_label",
                "kit_label",
            )
        }
    return {
        "gender_label": labels.optional_identifier_label(
            IdentifierKind.GENDER,
            detail.gender_id,
        ),
        "race_label": labels.race_label(detail.race_id),
        "class_label": labels.class_label(detail.class_id),
        "alignment_label": labels.optional_identifier_label(
            IdentifierKind.ALIGNMENT,
            detail.alignment_id,
        ),
        "enemy_ally_label": labels.optional_identifier_label(
            IdentifierKind.ENEMY_ALLY,
            detail.enemy_ally_id,
        ),
        "general_label": labels.optional_identifier_label(
            IdentifierKind.GENERAL,
            detail.general_id,
        ),
        "specific_label": labels.optional_identifier_label(
            IdentifierKind.SPECIFIC,
            detail.specific_id,
        ),
        "animation_label": labels.optional_identifier_label(
            IdentifierKind.ANIMATION,
            detail.animation_id,
        ),
        "racial_enemy_label": labels.favored_enemy_label(detail.racial_enemy_id),
        "kit_label": labels.kit_label(detail.kit_ids_value, detail.class_id),
    }


def character_dialogue_metrics(
    attribution: CharacterAttributionRecord | None,
    dialogues: Mapping[str, DialogueRecord],
) -> CharacterDialogueMetrics:
    if attribution is None:
        return CharacterDialogueMetrics()
    keys = {name.casefold() for name in attribution.resolved_dialogue_resource_names}
    resolved = [dialogues[key] for key in keys & dialogues.keys()]
    if not resolved:
        return CharacterDialogueMetrics(
            attribution_status=attribution.status,
            dialogue_status=attribution.dialogue_status,
            declared_dialogue_count=len(attribution.declared_dialogue_resrefs),
            resolved_dialogue_count=0,
        )
    totals = _dialogue_totals(resolved)
    return CharacterDialogueMetrics(
        attribution_status=attribution.status,
        dialogue_status=attribution.dialogue_status,
        declared_dialogue_count=len(attribution.declared_dialogue_resrefs),
        resolved_dialogue_count=len(resolved),
        dialogue_line_count=totals["lines"],
        npc_line_count=totals["npc"],
        player_line_count=totals["player"],
        journal_line_count=totals["journal"],
        dialogue_state_count=totals["states"],
        dialogue_transition_count=totals["transitions"],
        dialogue_serialized_size=totals["size"],
    )


def _dialogue_totals(dialogues: Sequence[DialogueRecord]) -> Counter[str]:
    totals: Counter[str] = Counter()
    for row in dialogues:
        if row.detail is None:
            continue
        totals.update(
            lines=row.detail.dialogue_line_count,
            npc=row.detail.npc_line_count,
            player=row.detail.player_line_count,
            journal=row.detail.journal_line_count,
            states=row.detail.state_count,
            transitions=row.detail.transition_count,
            size=row.serialized_size or 0,
        )
    return totals


def dialogue_row(
    record: DialogueRecord,
    character_count: int,
    directed_line_count: int = 0,
    generated_audio_count: int = 0,
) -> DialogueRow:
    detail = record.detail
    return DialogueRow(
        resource_name=record.resource_name,
        resref=record.resref,
        source_kind=record.source.kind,
        source_path=record.source.path,
        detail_status=record.extraction.status,
        detail_error=record.extraction.error,
        serialized_size=record.serialized_size,
        dialogue_line_count=(None if detail is None else detail.dialogue_line_count),
        npc_line_count=None if detail is None else detail.npc_line_count,
        player_line_count=None if detail is None else detail.player_line_count,
        journal_line_count=None if detail is None else detail.journal_line_count,
        character_count=character_count,
        directed_line_count=directed_line_count,
        generated_audio_count=generated_audio_count,
        updated_at=record.extraction.updated_at,
    )


def dialogue_line_row(
    record: DialogueLineRecord,
    dialogue: DialogueRecord,
    character_count: int,
    directions: list[DirectedLineRow] | None = None,
) -> DialogueLineRow:
    return DialogueLineRow(
        id=record.id,
        dialogue_resource_name=record.dialogue_resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source.kind,
        line_kind=record.line_kind,
        state_index=record.state_index,
        state_trigger_index=record.state_trigger_index,
        state_trigger_text=record.state_trigger_text,
        transition_index=record.transition_index,
        strref=record.strref,
        text=record.text,
        tokens=record.tokens,
        serialized_size=record.serialized_size,
        character_count=character_count,
        directions=directions or [],
    )


def transition_row(
    record: DialogueTransitionRecord,
    dialogue: DialogueRecord,
) -> TransitionRow:
    return TransitionRow(
        id=record.id,
        dialogue_resource_name=record.dialogue_resource_name,
        dialogue_resref=dialogue.resref,
        source_kind=dialogue.source.kind,
        state_index=record.state_index,
        transition_index=record.transition_index,
        flags_raw=record.flags_raw,
        flags_decoded=record.flags_decoded,
        trigger_index=record.trigger_index,
        trigger_text=record.trigger_text,
        action_index=record.action_index,
        action_text=record.action_text,
        next_dialog=record.next_dialog,
        next_state_index=record.next_state_index,
        terminates_dialog=record.terminates_dialog,
        serialized_size=record.serialized_size,
    )


def voice_row(
    record: VoiceResourceRecord,
    dialogues: Mapping[str, DialogueRecord],
    characters: Mapping[str, CharacterRecord],
    labels: LabelResolver,
    generated_voice: GeneratedVoiceRow | None = None,
    directed_line_count: int = 0,
    generated_audio_count: int = 0,
) -> VoiceRow:
    members = [
        characters[name.casefold()]
        for name in record.variant_resource_names
        if name.casefold() in characters
    ]
    representative = voice_representative(members)
    detail = representative.detail
    assert detail is not None
    prompt = record.prompt
    for heading, description in (
        ("Race description", labels.race_description(detail.race_id)),
        ("Class description", labels.class_description(detail.class_id)),
    ):
        prompt += f"\n\n{heading}:\n{description.strip() if description else 'unavailable'}"
    ordered_dialogues = [
        dialogues[resref.casefold()]
        for resref in record.dialogue_resrefs
        if resref.casefold() in dialogues
    ]
    return VoiceRow(
        id=record.voice_id,
        family_id=record.family_id,
        gender=record.gender,
        display_name=record.display_name,
        prompt=prompt,
        variant_resource_names=record.variant_resource_names,
        dialogue_resrefs=[row.resref for row in ordered_dialogues],
        variant_count=len(record.variant_resource_names),
        dialogue_count=len(ordered_dialogues),
        npc_line_count=sum(
            row.detail.npc_line_count for row in ordered_dialogues if row.detail is not None
        ),
        serialized_size=len(record.model_dump_json().encode("utf-8")),
        generated_voice=generated_voice,
        directed_line_count=directed_line_count,
        generated_audio_count=generated_audio_count,
    )
