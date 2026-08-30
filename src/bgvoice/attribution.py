"""Pure character-to-dialogue attribution and voice grouping."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from bgvoice.model_types import (
    BIOGRAPHY_SOUND_SLOT_ID,
    AttributionStatus,
    DetailStatus,
    DialogueLineKind,
    IdentifierKind,
    ProviderGender,
    ResourceTargetType,
    compose_search_text,
)
from bgvoice.pipeline_models import AttributionSummary
from bgvoice.storage_records import (
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterResourceLinkRecord,
    CharacterSoundRecord,
    DialogueLineRecord,
    DialogueRecord,
    IdentifierDefinitionRecord,
    VoiceResourceRecord,
)

_GENERIC_FAMILY_MIN_PROXIES = 10
_KNOWN_GENERIC_FAMILIES = frozenset(
    {
        "beggar",
        "beggar child",
        "citizen",
        "civil servant",
        "cowled enforcer",
        "crusader patrol",
        "cultist",
        "dark moon monk",
        "diseased child",
        "diseased one",
        "drow warrior",
        "elf",
        "elven warrior",
        "flaming fist healer",
        "flaming fist mercenary",
        "flaming fist veteran",
        "guardian",
        "mercenary captain",
        "moneylender",
        "mourner",
        "mugger",
        "onlooker",
        "patron",
        "prophet",
        "slave",
        "spectral harpist",
        "tavern patron",
        "troll",
    }
)
_VOICE_VARIANT_MIN_PROXIES = 2
_VOICE_VARIANT_MIN_TEXTS = 6
_NEUTRAL_VARIANT_MIN_DIALOGUES = 2


@dataclass(frozen=True, slots=True)
class AttributionBuild:
    records: list[CharacterAttributionRecord]
    voices: list[VoiceResourceRecord]
    summary: AttributionSummary


@dataclass(frozen=True, slots=True)
class _SpeakerProxy:
    genders: frozenset[ProviderGender]
    texts: frozenset[str]


@dataclass(frozen=True, slots=True)
class _VoiceDraft:
    family_id: str
    gender: ProviderGender | None
    voice_id: str
    display_name: str
    prompt: str
    members: tuple[CharacterRecord, ...]
    dialogues: tuple[DialogueRecord, ...]
    biography_sound_id: str | None


def build_attributions(
    run_id: str,
    characters: Sequence[CharacterRecord],
    dialogues: Sequence[DialogueRecord],
    dialogue_lines: Sequence[DialogueLineRecord],
    character_sounds: Sequence[CharacterSoundRecord],
    links: Sequence[CharacterResourceLinkRecord],
    identifiers: Sequence[IdentifierDefinitionRecord],
) -> AttributionBuild:
    """Build a complete immutable attribution publication in memory."""
    records = _attribution_records(run_id, characters, dialogues, links)
    summary = _attribution_summary(run_id, records, dialogues)
    voices = [
        _voice_resource_record(run_id, voice)
        for voice in _voice_resources(
            characters,
            dialogues,
            dialogue_lines,
            character_sounds,
            identifiers,
            records,
        )
    ]
    return AttributionBuild(records, voices, summary)


def _attribution_records(
    run_id: str,
    characters: Sequence[CharacterRecord],
    dialogues: Sequence[DialogueRecord],
    links: Sequence[CharacterResourceLinkRecord],
) -> list[CharacterAttributionRecord]:
    dialogues_by_resref = {dialogue.resref.casefold(): dialogue for dialogue in dialogues}
    links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]] = {}
    for link in links:
        if link.target_type is ResourceTargetType.DIALOGUE:
            links_by_death_variable.setdefault(link.death_variable.casefold(), []).append(link)

    records: list[CharacterAttributionRecord] = []
    for character in characters:
        declared = _character_dialogue_resrefs(character, links_by_death_variable)
        resolved = tuple(
            dialogues_by_resref[resref.casefold()]
            for resref in declared
            if resref.casefold() in dialogues_by_resref
        )
        records.append(_character_attribution_record(run_id, character, declared, resolved))
    return records


def _character_dialogue_resrefs(
    character: CharacterRecord,
    links_by_death_variable: dict[str, list[CharacterResourceLinkRecord]],
) -> tuple[str, ...]:
    resrefs: dict[str, str] = {}
    detail = character.detail
    if detail is None:
        return ()
    if detail.dialog_resref is not None:
        resrefs[detail.dialog_resref.casefold()] = detail.dialog_resref
    if detail.death_variable is not None:
        for link in links_by_death_variable.get(detail.death_variable.casefold(), []):
            resrefs.setdefault(link.target_resref.casefold(), link.target_resref)
    return tuple(sorted(resrefs.values(), key=lambda value: (value.casefold(), value)))


def _character_attribution_record(
    run_id: str,
    character: CharacterRecord,
    declared_resrefs: tuple[str, ...],
    dialogues: tuple[DialogueRecord, ...],
) -> CharacterAttributionRecord:
    resolved_resrefs = {dialogue.resref.casefold() for dialogue in dialogues}
    missing_resrefs = [
        resref for resref in declared_resrefs if resref.casefold() not in resolved_resrefs
    ]
    return CharacterAttributionRecord(
        key=CharacterAttributionRecord.key_for(run_id, character.resource_name),
        run_id=run_id,
        character_resource_name=character.resource_name,
        status=_attribution_status(character, declared_resrefs, missing_resrefs),
        dialogue_status=_dialogue_status(dialogues),
        declared_dialogue_resrefs=list(declared_resrefs),
        missing_dialogue_resrefs=missing_resrefs,
        resolved_dialogue_resource_names=[dialogue.resource_name for dialogue in dialogues],
    )


def _attribution_status(
    character: CharacterRecord,
    declared_resrefs: tuple[str, ...],
    missing_resrefs: Sequence[str],
) -> AttributionStatus:
    if character.detail is None:
        return AttributionStatus.CHARACTER_UNAVAILABLE
    if not declared_resrefs:
        return AttributionStatus.NO_DIALOGUE
    if len(missing_resrefs) == len(declared_resrefs):
        return AttributionStatus.MISSING_DIALOGUE
    if missing_resrefs:
        return AttributionStatus.PARTIAL_MATCH
    return AttributionStatus.MATCHED


def _dialogue_status(dialogues: Sequence[DialogueRecord]) -> DetailStatus | None:
    statuses = {dialogue.extraction.status for dialogue in dialogues}
    if DetailStatus.FAILED in statuses:
        return DetailStatus.FAILED
    if DetailStatus.PENDING in statuses:
        return DetailStatus.PENDING
    return DetailStatus.COMPLETE if statuses else None


def _attribution_summary(
    run_id: str,
    records: Sequence[CharacterAttributionRecord],
    dialogues: Sequence[DialogueRecord],
) -> AttributionSummary:
    statuses = Counter(record.status for record in records)
    attributed_names = {
        resource_name.casefold()
        for record in records
        for resource_name in record.resolved_dialogue_resource_names
    }
    attributed = [
        dialogue for dialogue in dialogues if dialogue.resource_name.casefold() in attributed_names
    ]
    unattributed = [
        dialogue
        for dialogue in dialogues
        if dialogue.resource_name.casefold() not in attributed_names
    ]
    return AttributionSummary(
        run_id=run_id,
        characters_total=len(records),
        characters_matched=statuses[AttributionStatus.MATCHED],
        characters_partially_matched=statuses[AttributionStatus.PARTIAL_MATCH],
        characters_missing_dialogue=statuses[AttributionStatus.MISSING_DIALOGUE],
        characters_dialogue_failed=sum(
            record.dialogue_status is DetailStatus.FAILED for record in records
        ),
        characters_without_dialogue=statuses[AttributionStatus.NO_DIALOGUE],
        characters_unavailable=statuses[AttributionStatus.CHARACTER_UNAVAILABLE],
        dialogues_total=len(dialogues),
        dialogues_attributed=len(attributed),
        dialogues_unattributed=len(unattributed),
        attributed_dialogue_lines=sum(
            dialogue.detail.dialogue_line_count
            for dialogue in attributed
            if dialogue.detail is not None
        ),
        unattributed_dialogue_lines=sum(
            dialogue.detail.dialogue_line_count
            for dialogue in unattributed
            if dialogue.detail is not None
        ),
    )


def _voice_resources(
    characters: Sequence[CharacterRecord],
    dialogues: Sequence[DialogueRecord],
    dialogue_lines: Sequence[DialogueLineRecord],
    character_sounds: Sequence[CharacterSoundRecord],
    identifiers: Sequence[IdentifierDefinitionRecord],
    attributions: Sequence[CharacterAttributionRecord],
) -> list[_VoiceDraft]:
    members_by_voice: dict[str, list[CharacterRecord]] = {}
    for character in characters:
        if character.detail is not None:
            members_by_voice.setdefault(character.detail.display_name.casefold(), []).append(
                character
            )

    attribution_by_character = {
        attribution.character_resource_name.casefold(): attribution for attribution in attributions
    }
    dialogues_by_resource = {dialogue.resource_name.casefold(): dialogue for dialogue in dialogues}
    texts_by_dialogue: dict[str, set[str]] = {}
    for line in dialogue_lines:
        if line.line_kind is DialogueLineKind.NPC and line.text and line.text.strip():
            texts_by_dialogue.setdefault(line.dialogue_resource_name.casefold(), set()).add(
                line.text
            )
    labels: dict[tuple[IdentifierKind, int], str] = {}
    for definition in identifiers:
        display_names = [
            " ".join(part.capitalize() for part in symbol.replace("-", "_").split("_") if part)
            for symbol in definition.symbols
        ]
        labels[(definition.kind, definition.value)] = " / ".join(display_names)

    families = (
        _voice_family(
            family_id,
            members,
            attribution_by_character,
            dialogues_by_resource,
            texts_by_dialogue,
            character_sounds,
            labels,
        )
        for family_id, members in sorted(members_by_voice.items())
    )
    return [resource for family in families for resource in family]


def _voice_family(
    family_id: str,
    members: Sequence[CharacterRecord],
    attribution_by_character: dict[str, CharacterAttributionRecord],
    dialogues_by_resource: dict[str, DialogueRecord],
    texts_by_dialogue: dict[str, set[str]],
    character_sounds: Sequence[CharacterSoundRecord],
    labels: dict[tuple[IdentifierKind, int], str],
) -> list[_VoiceDraft]:
    members = sorted(members, key=lambda member: member.resource_name.casefold())
    dialogues = _voice_dialogues(members, attribution_by_character, dialogues_by_resource)
    if not dialogues:
        return []

    split = _gender_split(family_id, members, attribution_by_character, texts_by_dialogue)
    if split is None:
        representative = voice_representative(members)
        detail = representative.detail
        assert detail is not None
        contributing_genders = {
            ProviderGender.from_engine_id(member.detail.gender_id)
            for member in members
            if member.detail is not None
            and any(
                name.casefold() in texts_by_dialogue
                for name in attribution_by_character[
                    member.resource_name.casefold()
                ].resolved_dialogue_resource_names
            )
        }
        return [
            _voice_draft(
                family_id,
                next(iter(contributing_genders)) if len(contributing_genders) == 1 else None,
                family_id,
                detail.display_name,
                members,
                dialogues,
                character_sounds,
                labels,
            )
        ]

    exclusive_dialogues, mixed_dialogues = split
    dialogue_by_name = {dialogue.resource_name.casefold(): dialogue for dialogue in dialogues}
    dialogues_by_gender = {
        gender: set(dialogue_names) for gender, dialogue_names in exclusive_dialogues.items()
    }
    if mixed_dialogues:
        dialogues_by_gender.setdefault(ProviderGender.NEUTRAL, set()).update(mixed_dialogues)
    drafts: list[_VoiceDraft] = []
    for gender in sorted(dialogues_by_gender, key=lambda value: value.value):
        dialogue_names = dialogues_by_gender[gender]
        voice_members = [
            member
            for member in members
            if dialogue_names
            & {
                name.casefold()
                for name in attribution_by_character[
                    member.resource_name.casefold()
                ].resolved_dialogue_resource_names
            }
        ]
        representative = voice_representative(voice_members)
        detail = representative.detail
        assert detail is not None
        drafts.append(
            _voice_draft(
                family_id,
                gender,
                f"{family_id}~g={gender.value}",
                f"{detail.display_name} · {gender.value.title()}",
                voice_members,
                [dialogue_by_name[name] for name in sorted(dialogue_names)],
                character_sounds,
                labels,
            )
        )
    return drafts


def _voice_draft(
    family_id: str,
    gender: ProviderGender | None,
    voice_id: str,
    display_name: str,
    members: Sequence[CharacterRecord],
    dialogues: Sequence[DialogueRecord],
    character_sounds: Sequence[CharacterSoundRecord],
    labels: dict[tuple[IdentifierKind, int], str],
) -> _VoiceDraft:
    representative = voice_representative(members)
    biography = _voice_biography(members, character_sounds)
    prompt = _voice_prompt(representative, gender, labels)
    if biography is not None:
        biography_text = biography.text
        assert biography_text is not None
        prompt = f"{prompt}\n\nBiography:\n{biography_text.strip()}"
    return _VoiceDraft(
        family_id=family_id,
        gender=gender,
        voice_id=voice_id,
        display_name=display_name,
        prompt=prompt,
        members=tuple(members),
        dialogues=tuple(dialogues),
        biography_sound_id=biography.id if biography is not None else None,
    )


def _gender_split(
    family_id: str,
    members: Sequence[CharacterRecord],
    attribution_by_character: dict[str, CharacterAttributionRecord],
    texts_by_dialogue: dict[str, set[str]],
) -> tuple[dict[ProviderGender, frozenset[str]], frozenset[str]] | None:
    proxies = _speaker_proxies(members, attribution_by_character, texts_by_dialogue)
    if not proxies:
        return None
    known_generic = family_id in _KNOWN_GENERIC_FAMILIES
    if not known_generic and len(proxies) < _GENERIC_FAMILY_MIN_PROXIES:
        return None

    family_texts = set().union(*(proxy.texts for proxy in proxies))
    largest_proxy = max(len(proxy.texts) for proxy in proxies)
    if not known_generic and largest_proxy * 3 >= len(family_texts) * 2:
        return None

    owners: dict[str, set[ProviderGender]] = {}
    for member in members:
        detail = member.detail
        assert detail is not None
        gender = ProviderGender.from_engine_id(detail.gender_id)
        attribution = attribution_by_character[member.resource_name.casefold()]
        for name in attribution.resolved_dialogue_resource_names:
            dialogue_name = name.casefold()
            if dialogue_name in texts_by_dialogue:
                owners.setdefault(dialogue_name, set()).add(gender)

    exclusive: dict[ProviderGender, frozenset[str]] = {}
    for gender in ProviderGender:
        pure_proxies = sum(proxy.genders == {gender} for proxy in proxies)
        dialogue_names = frozenset(name for name, genders in owners.items() if genders == {gender})
        texts = set().union(*(texts_by_dialogue[name] for name in dialogue_names))
        if texts and (
            known_generic
            or (
                pure_proxies >= _VOICE_VARIANT_MIN_PROXIES
                and len(texts) >= _VOICE_VARIANT_MIN_TEXTS
                and (
                    gender is not ProviderGender.NEUTRAL
                    or len(dialogue_names) >= _NEUTRAL_VARIANT_MIN_DIALOGUES
                )
            )
        ):
            exclusive[gender] = dialogue_names

    if len(exclusive) < 2:
        return None
    all_dialogues = frozenset(owners)
    specialized = frozenset(name for names in exclusive.values() for name in names)
    return exclusive, all_dialogues - specialized


def _speaker_proxies(
    members: Sequence[CharacterRecord],
    attribution_by_character: dict[str, CharacterAttributionRecord],
    texts_by_dialogue: dict[str, set[str]],
) -> list[_SpeakerProxy]:
    groups: list[tuple[set[tuple[str, str]], list[CharacterRecord]]] = []
    for member in members:
        attribution = attribution_by_character[member.resource_name.casefold()]
        dialogue_names = {
            name.casefold()
            for name in attribution.resolved_dialogue_resource_names
            if name.casefold() in texts_by_dialogue
        }
        if not dialogue_names:
            continue
        detail = member.detail
        assert detail is not None
        tokens = {("dialogue", name) for name in dialogue_names}
        death_variable = (detail.death_variable or "").strip().casefold()
        if death_variable and death_variable != "none":
            tokens.add(("death_variable", death_variable))

        matches = [index for index, (known, _members) in enumerate(groups) if known & tokens]
        if not matches:
            groups.append((tokens, [member]))
            continue
        target = matches[0]
        groups[target][0].update(tokens)
        groups[target][1].append(member)
        for index in reversed(matches[1:]):
            groups[target][0].update(groups[index][0])
            groups[target][1].extend(groups[index][1])
            groups.pop(index)

    proxies: list[_SpeakerProxy] = []
    for _tokens, proxy_members in groups:
        dialogue_names = frozenset(
            name.casefold()
            for member in proxy_members
            for name in attribution_by_character[
                member.resource_name.casefold()
            ].resolved_dialogue_resource_names
            if name.casefold() in texts_by_dialogue
        )
        proxies.append(
            _SpeakerProxy(
                genders=frozenset(
                    ProviderGender.from_engine_id(member.detail.gender_id)
                    for member in proxy_members
                    if member.detail is not None
                ),
                texts=frozenset(
                    text for name in dialogue_names for text in texts_by_dialogue[name]
                ),
            )
        )
    return proxies


def _voice_dialogues(
    members: Sequence[CharacterRecord],
    attribution_by_character: dict[str, CharacterAttributionRecord],
    dialogues_by_resource: dict[str, DialogueRecord],
) -> list[DialogueRecord]:
    dialogues: dict[str, DialogueRecord] = {}
    for member in members:
        attribution = attribution_by_character[member.resource_name.casefold()]
        for resource_name in attribution.resolved_dialogue_resource_names:
            dialogue = dialogues_by_resource[resource_name.casefold()]
            if dialogue.detail is not None and dialogue.detail.npc_line_count > 0:
                dialogues.setdefault(dialogue.resref.casefold(), dialogue)
    return sorted(dialogues.values(), key=lambda dialogue: dialogue.resref.casefold())


def _voice_biography(
    members: Sequence[CharacterRecord],
    character_sounds: Sequence[CharacterSoundRecord],
) -> CharacterSoundRecord | None:
    """Choose the longest distinct personal biography among a voice's CREs."""
    member_names = {member.resource_name.casefold() for member in members}
    candidates = (
        sound
        for sound in character_sounds
        if sound.character_resource_name.casefold() in member_names
        and sound.slot_id == BIOGRAPHY_SOUND_SLOT_ID
        and sound.text is not None
        and bool(sound.text.strip())
    )
    return min(
        candidates,
        key=_biography_priority,
        default=None,
    )


def _biography_priority(sound: CharacterSoundRecord) -> tuple[int, int, str, str]:
    text = sound.text
    assert text is not None
    return (
        -len(text.strip()),
        sound.strref,
        sound.character_resource_name.casefold(),
        sound.character_resource_name,
    )


def voice_representative(members: Sequence[CharacterRecord]) -> CharacterRecord:
    """Choose one real CRE for both the canonical name and prompt metadata."""
    assert all(character.detail is not None for character in members)
    metadata_counts = Counter(_voice_metadata(character) for character in members)
    return min(
        members,
        key=lambda character: (
            character.detail is None
            or (character.detail.short_name is None and character.detail.long_name is None),
            -metadata_counts[_voice_metadata(character)],
            character.resource_name.casefold(),
            character.resource_name,
        ),
    )


def _voice_metadata(character: CharacterRecord) -> tuple[int, int, int, int | None, int]:
    detail = character.detail
    assert detail is not None
    return (
        detail.gender_id,
        detail.race_id,
        detail.class_id,
        detail.kit_ids_value,
        detail.alignment_id,
    )


def _voice_prompt(
    character: CharacterRecord,
    gender: ProviderGender | None,
    labels: dict[tuple[IdentifierKind, int], str],
) -> str:
    detail = character.detail
    assert detail is not None
    gender_name = (
        gender.value.title()
        if gender is not None
        else labels.get((IdentifierKind.GENDER, detail.gender_id), str(detail.gender_id))
    )
    lines = [
        f"Name: {detail.display_name}",
        f"Gender: {gender_name}",
        f"Race: {labels.get((IdentifierKind.RACE, detail.race_id), str(detail.race_id))}",
        f"Class: {labels.get((IdentifierKind.CLASS, detail.class_id), str(detail.class_id))}",
    ]
    kit_id = detail.kit_ids_value
    if kit_id not in (None, 0, 0x4000):
        lines.append(f"Kit: {labels.get((IdentifierKind.KIT, kit_id), str(kit_id))}")
    lines.append(
        f"Alignment: {labels.get((IdentifierKind.ALIGNMENT, detail.alignment_id), str(detail.alignment_id))}"
    )
    return "\n".join(lines)


def _voice_resource_record(
    run_id: str,
    resource: _VoiceDraft,
) -> VoiceResourceRecord:
    return VoiceResourceRecord(
        key=VoiceResourceRecord.key_for(run_id, resource.voice_id),
        run_id=run_id,
        voice_id=resource.voice_id,
        family_id=resource.family_id,
        gender=resource.gender,
        display_name=resource.display_name,
        prompt=resource.prompt,
        variant_resource_names=[member.resource_name for member in resource.members],
        dialogue_resrefs=[dialogue.resref for dialogue in resource.dialogues],
        biography_sound_id=resource.biography_sound_id,
        search_text=compose_search_text(
            resource.voice_id,
            resource.family_id,
            resource.display_name,
            resource.prompt,
            resource.biography_sound_id,
            *(member.resource_name for member in resource.members),
            *(dialogue.resref for dialogue in resource.dialogues),
        ),
    )
