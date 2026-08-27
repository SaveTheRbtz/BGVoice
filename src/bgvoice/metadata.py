"""Import normalized metadata from the effective Infinity Engine resources.

The parsers follow the effective resources selected by the game installation. Format and
column semantics are documented by IESDP:

* IDS: https://gibberlings3.github.io/iesdp/file_formats/general.htm#ids
* 2DA: https://gibberlings3.github.io/iesdp/file_formats/ie_formats/2da.htm
* RACETEXT: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/racetext.htm
* CLASTEXT: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/clastext.htm
* KITLIST: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/kitlist.htm
* CAMPAIGN: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/campaign.htm
* INTERDIA: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/interdia.htm
* PDIALOG: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/pdialog.htm
* INTERACT: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/interact.htm
* CHARSND: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/charsnd.htm
* CSOUND: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/csound.htm
* ENGINEST: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/enginest.htm
* MONTHS: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/months.htm
* YEARS: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/years.htm
* SPEECH: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/speech.htm
* HATERACE: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/haterace.htm
* HAPPY: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/happy.htm
* BANTTIMG: https://gibberlings3.github.io/iesdp/files/2da/2da_bgee/banttimg.htm
"""

import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from bgvoice.iecli import MetadataIeCliClient
from bgvoice.models import (
    BanterTimingSettings,
    CampaignCalendarDefinition,
    CampaignDefinition,
    CampaignResourceBinding,
    CampaignResourceKind,
    CharacterResourceLink,
    CharacterResourceRole,
    ClassId,
    ClassTextKitId,
    ClassTextRow,
    EngineString,
    FavoredEnemyDefinition,
    HappinessAlignment,
    HappinessRule,
    IdentifierDefinition,
    IdentifierKind,
    InteractionKind,
    InteractionRule,
    KitDefinition,
    KitIdsValue,
    KitListRowId,
    MetadataExtraction,
    MonthDefinition,
    RaceId,
    RaceTextRow,
    ResourceTargetType,
    SoundsetLine,
    SoundSlotGroup,
    SoundSlotId,
    SoundSlotSuffix,
    class_text_kit_id_from_kit_ids,
)

_IDS_MAPPING = re.compile(r"^\s*(0[xX][0-9A-Fa-f]+|[0-9]+)\s+(\S+)")
_TOKEN = re.compile(r'"([^"]*)"|(\S+)')

_IDENTIFIER_RESOURCES: tuple[tuple[IdentifierKind, str], ...] = (
    (IdentifierKind.RACE, "RACE.IDS"),
    (IdentifierKind.CLASS, "CLASS.IDS"),
    (IdentifierKind.GENDER, "GENDER.IDS"),
    (IdentifierKind.ALIGNMENT, "ALIGNMEN.IDS"),
    (IdentifierKind.ENEMY_ALLY, "EA.IDS"),
    (IdentifierKind.GENERAL, "GENERAL.IDS"),
    (IdentifierKind.SPECIFIC, "SPECIFIC.IDS"),
    (IdentifierKind.ANIMATION, "ANIMATE.IDS"),
    (IdentifierKind.KIT, "KIT.IDS"),
    (IdentifierKind.SOUND_SLOT, "SNDSLOT.IDS"),
)

_CAMPAIGN_RESOURCE_COLUMNS = (
    (CampaignResourceKind.BANTER_DIALOGUES, "INTERDIA"),
    (CampaignResourceKind.PARTY_DIALOGUES, "PDIALOG"),
    (CampaignResourceKind.INTERACTIONS, "INTERACT"),
    (CampaignResourceKind.CALENDAR, "YEARS"),
    (CampaignResourceKind.CLASS_TEXT, "CLASTEXT"),
    (CampaignResourceKind.RACE_TEXT, "RACETEXT"),
)
_RACE_TEXT_COLUMNS = ("ID", "NAME", "DESCSTR", "UPPERCASE", "BIOGRAPHY")
_CLASS_TEXT_COLUMNS = (
    "CLASSID",
    "KITID",
    "LOWER",
    "DESCSTR",
    "MIXED",
    "BIOGRAPHY",
    "FALLEN",
    "BRIEFDESC",
    "FALLEN_NOTICE",
)
_KITLIST_COLUMNS = (
    "ROWNAME",
    "LOWER",
    "MIXED",
    "HELP",
    "ABILITIES",
    "PROFICIENCY",
    "UNUSABLE",
    "CLASS",
    "KITIDS",
)
_PARTY_DIALOGUE_COLUMNS = (
    "POST_DIALOG_FILE",
    "JOIN_DIALOG_FILE",
    "DREAM_SCRIPT_FILE",
)
_PARTY_DIALOGUE_OPTIONAL_COLUMNS = (
    "25POST_DIALOG_FILE",
    "25JOIN_DIALOG_FILE",
    "25DREAM_SCRIPT_FILE",
    "25OVERRIDE_SCRIPT_FILE",
)
_CSOUND_COLUMNS = ("LETTER",)
_ENGINE_STRING_COLUMNS = ("StrRef",)
_MONTH_COLUMNS = ("DAYS", "NAME")
_CALENDAR_COLUMNS = ("VALUE",)
_SPEECH_COLUMNS = ("OFFSET", "NUM")
_FAVORED_ENEMY_COLUMNS = ("STRREF", "IDS", "STRREF_HELP")
_HAPPINESS_COLUMNS = ("GOOD", "NEUTRAL", "EVIL")
_BANTER_TIMING_COLUMNS = ("VALUE",)
_BANTER_TIMING_ROWS = (
    "FREQUENCY",
    "PROBABILITY",
    "REPLAYDELAY",
    "SPECIALPROBABILITY",
)


@dataclass(frozen=True, slots=True)
class TwoDaRow:
    """One positionally parsed 2DA row."""

    ordinal: int
    row_name: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TwoDaTable:
    """A positional 2DA representation that preserves duplicate column names."""

    source_resource: str
    default_value: str
    columns: tuple[str, ...]
    rows: tuple[TwoDaRow, ...]


@dataclass(frozen=True, slots=True)
class _RawRaceText:
    source_resource: str
    ordinal: int
    row_name: str
    race_id: int
    name_strref: int | None
    description_strref: int | None
    uppercase_name_strref: int | None
    biography_strref: int | None


@dataclass(frozen=True, slots=True)
class _RawClassText:
    source_resource: str
    ordinal: int
    row_name: str
    class_id: int
    class_text_kit_id: int
    lower_name_strref: int | None
    description_strref: int | None
    mixed_name_strref: int | None
    biography_strref: int | None
    fallen: bool
    brief_description_strref: int | None
    fallen_notice_strref: int | None


@dataclass(frozen=True, slots=True)
class _RawKit:
    source_resource: str
    ordinal: int
    row_id: int
    row_name: str
    lower_name_strref: int | None
    mixed_name_strref: int | None
    help_strref: int | None
    abilities: str | None
    proficiency: int | None
    unusable: int | None
    class_id: int | None
    kit_ids_value: int | None
    class_text_kit_id: int | None


@dataclass(frozen=True, slots=True)
class _RawSoundsetLine:
    source_resource: str
    soundset_name: str
    slot_id: SoundSlotId
    strref: int


@dataclass(frozen=True, slots=True)
class _RawFavoredEnemy:
    source_resource: str
    ordinal: int
    row_name: str
    name_strref: int
    race_id: int
    help_strref: int


@dataclass(frozen=True, slots=True)
class _RawEngineString:
    source_resource: str
    ordinal: int
    key: str
    strref: int | None


@dataclass(frozen=True, slots=True)
class _RawMonth:
    source_resource: str
    ordinal: int
    month_id: int
    days: int
    name_strref: int


@dataclass(frozen=True, slots=True)
class _RawCalendar:
    source_resource: str
    start_time: int
    start_year: int
    normal_format_strref: int
    special_format_strref: int


def parse_ids(
    text: str,
    *,
    kind: IdentifierKind,
    source_resource: str,
) -> list[IdentifierDefinition]:
    """Parse decimal/hex IDS mappings and group aliases by value in source order."""
    grouped: dict[int, tuple[int, list[str]]] = {}
    mapping_ordinal = 0
    for line in text.lstrip("\ufeff").splitlines():
        match = _IDS_MAPPING.match(line)
        if match is None:
            continue
        value = _parse_uint(match.group(1), field="IDS value")
        symbol = match.group(2)
        if value not in grouped:
            grouped[value] = (mapping_ordinal, [])
        grouped[value][1].append(symbol)
        mapping_ordinal += 1

    return [
        IdentifierDefinition(
            kind=kind,
            value=value,
            source_resource=source_resource,
            ordinal=ordinal,
            symbols=symbols,
        )
        for value, (ordinal, symbols) in grouped.items()
    ]


def parse_2da(text: str, *, source_resource: str) -> TwoDaTable:
    """Parse 2DA text positionally, retaining duplicate column names and row order."""
    lines = [
        line.strip()
        for line in text.lstrip("\ufeff").splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]
    assert len(lines) >= 3, f"{source_resource} is missing its 2DA header"
    assert tuple(token.upper() for token in _tokens(lines[0])) == (
        "2DA",
        "V1.0",
    ), f"{source_resource} does not begin with a 2DA V1.0 header"

    default_tokens = _tokens(lines[1])
    assert len(default_tokens) == 1, f"{source_resource} has an invalid 2DA default value line"
    columns = _tokens(lines[2])
    assert columns, f"{source_resource} has no 2DA columns"

    rows: list[TwoDaRow] = []
    for ordinal, line in enumerate(lines[3:]):
        tokens = _tokens(line)
        assert tokens and tokens[0], f"{source_resource} row {ordinal} is missing its row label"
        values = tokens[1:]
        assert len(values) <= len(columns), (
            f"{source_resource} row {ordinal} has {len(values)} cells; expected at most "
            f"{len(columns)}"
        )
        padded_values = values + (default_tokens[0],) * (len(columns) - len(values))
        rows.append(TwoDaRow(ordinal, tokens[0], padded_values))
    return TwoDaTable(source_resource, default_tokens[0], columns, tuple(rows))


def build_metadata(
    client: MetadataIeCliClient,
    game_root: Path,
    *,
    workers: int = 8,
) -> MetadataExtraction:
    """Read effective metadata resources and resolve their unique TLK references."""
    assert workers >= 1, "workers must be at least 1"
    root = game_root.expanduser().resolve()
    resources: dict[str, str] = {}

    def read(resource_name: str) -> str:
        canonical_name = resource_name.upper()
        if canonical_name not in resources:
            resources[canonical_name] = client.read_text_resource(root, canonical_name)
        return resources[canonical_name]

    identifiers = [
        definition
        for kind, resource_name in _IDENTIFIER_RESOURCES
        for definition in parse_ids(
            read(resource_name),
            kind=kind,
            source_resource=resource_name,
        )
    ]

    campaign_table = parse_2da(read("CAMPAIGN.2DA"), source_resource="CAMPAIGN.2DA")
    campaigns, bindings = _project_campaigns(campaign_table)

    raw_race_rows: list[_RawRaceText] = []
    raw_class_rows: list[_RawClassText] = []
    character_resource_links: list[CharacterResourceLink] = []
    interaction_rules: list[InteractionRule] = []
    raw_calendars: list[_RawCalendar] = []
    for resource_resref in _ordered_bound_resources(bindings, CampaignResourceKind.RACE_TEXT):
        resource_name = f"{resource_resref}.2DA"
        raw_race_rows.extend(
            _project_race_text(parse_2da(read(resource_name), source_resource=resource_name))
        )
    for resource_resref in _ordered_bound_resources(bindings, CampaignResourceKind.CLASS_TEXT):
        resource_name = f"{resource_resref}.2DA"
        raw_class_rows.extend(
            _project_class_text(parse_2da(read(resource_name), source_resource=resource_name))
        )
    for resource_resref in _ordered_bound_resources(
        bindings, CampaignResourceKind.BANTER_DIALOGUES
    ):
        resource_name = f"{resource_resref}.2DA"
        character_resource_links.extend(
            _project_banter_links(parse_2da(read(resource_name), source_resource=resource_name))
        )
    for resource_resref in _ordered_bound_resources(bindings, CampaignResourceKind.PARTY_DIALOGUES):
        resource_name = f"{resource_resref}.2DA"
        character_resource_links.extend(
            _project_party_dialogue_links(
                parse_2da(read(resource_name), source_resource=resource_name)
            )
        )
    for resource_resref in _ordered_bound_resources(bindings, CampaignResourceKind.INTERACTIONS):
        resource_name = f"{resource_resref}.2DA"
        interaction_rules.extend(
            _project_interaction_rules(
                parse_2da(read(resource_name), source_resource=resource_name)
            )
        )
    for resource_resref in _ordered_bound_resources(bindings, CampaignResourceKind.CALENDAR):
        resource_name = f"{resource_resref}.2DA"
        raw_calendars.append(
            _project_calendar(parse_2da(read(resource_name), source_resource=resource_name))
        )

    raw_kits = _project_kitlist(parse_2da(read("KITLIST.2DA"), source_resource="KITLIST.2DA"))
    raw_soundset_lines = _project_soundset_lines(
        parse_2da(read("CHARSND.2DA"), source_resource="CHARSND.2DA")
    )
    sound_slot_suffixes = _project_sound_slot_suffixes(
        parse_2da(read("CSOUND.2DA"), source_resource="CSOUND.2DA")
    )
    raw_engine_strings = _project_engine_strings(
        parse_2da(read("ENGINEST.2DA"), source_resource="ENGINEST.2DA")
    )
    raw_months = _project_months(parse_2da(read("MONTHS.2DA"), source_resource="MONTHS.2DA"))
    sound_slot_groups = _project_sound_slot_groups(
        parse_2da(read("SPEECH.2DA"), source_resource="SPEECH.2DA")
    )
    raw_favored_enemies = _project_favored_enemies(
        parse_2da(read("HATERACE.2DA"), source_resource="HATERACE.2DA")
    )
    happiness_rules = _project_happiness_rules(
        parse_2da(read("HAPPY.2DA"), source_resource="HAPPY.2DA")
    )
    banter_timing = _project_banter_timing(
        parse_2da(read("BANTTIMG.2DA"), source_resource="BANTTIMG.2DA")
    )
    strrefs = sorted(
        _metadata_strrefs(
            raw_race_rows,
            raw_class_rows,
            raw_kits,
            raw_soundset_lines,
            raw_engine_strings,
            raw_months,
            raw_calendars,
            raw_favored_enemies,
        )
    )
    resolved = _resolve_strings(client, root, strrefs, workers=workers)

    return MetadataExtraction(
        source_resource_count=len(resources),
        resolved_strref_count=len(resolved),
        identifiers=identifiers,
        campaigns=campaigns,
        campaign_resource_bindings=bindings,
        character_resource_links=character_resource_links,
        interaction_rules=interaction_rules,
        soundset_lines=[_resolve_soundset_line(row, resolved) for row in raw_soundset_lines],
        sound_slot_suffixes=sound_slot_suffixes,
        sound_slot_groups=sound_slot_groups,
        favored_enemies=[_resolve_favored_enemy(row, resolved) for row in raw_favored_enemies],
        happiness_rules=happiness_rules,
        banter_timing=banter_timing,
        engine_strings=[_resolve_engine_string(row, resolved) for row in raw_engine_strings],
        months=[_resolve_month(row, resolved) for row in raw_months],
        campaign_calendars=[_resolve_calendar(row, resolved) for row in raw_calendars],
        race_text_rows=[_resolve_race_text(row, resolved) for row in raw_race_rows],
        class_text_rows=[_resolve_class_text(row, resolved) for row in raw_class_rows],
        kits=[_resolve_kit(row, resolved) for row in raw_kits],
    )


def _project_campaigns(
    table: TwoDaTable,
) -> tuple[list[CampaignDefinition], list[CampaignResourceBinding]]:
    column_indices = _require_columns(
        table,
        tuple(column for _kind, column in _CAMPAIGN_RESOURCE_COLUMNS),
    )
    campaigns: list[CampaignDefinition] = []
    bindings: list[CampaignResourceBinding] = []
    for row in table.rows:
        campaigns.append(
            CampaignDefinition(
                campaign_id=row.row_name,
                source_resource=table.source_resource,
                ordinal=row.ordinal,
            )
        )
        for (kind, _column), index in zip(
            _CAMPAIGN_RESOURCE_COLUMNS,
            column_indices,
            strict=True,
        ):
            bindings.append(
                CampaignResourceBinding(
                    campaign_id=row.row_name,
                    resource_kind=kind,
                    resource_resref=_target_resref(row.values[index]),
                )
            )
    return campaigns, bindings


def _project_race_text(table: TwoDaTable) -> list[_RawRaceText]:
    race_id, name, description, uppercase_name, biography = _require_columns(
        table, _RACE_TEXT_COLUMNS
    )
    return [
        _RawRaceText(
            source_resource=table.source_resource,
            ordinal=row.ordinal,
            row_name=row.row_name,
            race_id=_parse_uint(row.values[race_id], field="RACETEXT.ID", maximum=0xFF),
            name_strref=_parse_strref(row.values[name]),
            description_strref=_parse_strref(row.values[description]),
            uppercase_name_strref=_parse_strref(row.values[uppercase_name]),
            biography_strref=_parse_strref(row.values[biography]),
        )
        for row in table.rows
    ]


def _project_class_text(table: TwoDaTable) -> list[_RawClassText]:
    (
        class_id,
        kit_id,
        lower_name,
        description,
        mixed_name,
        biography,
        fallen_column,
        brief_description,
        fallen_notice,
    ) = _require_columns(table, _CLASS_TEXT_COLUMNS)
    rows: list[_RawClassText] = []
    for row in table.rows:
        fallen = _parse_uint(row.values[fallen_column], field="CLASTEXT.FALLEN", maximum=1)
        rows.append(
            _RawClassText(
                source_resource=table.source_resource,
                ordinal=row.ordinal,
                row_name=row.row_name,
                class_id=_parse_uint(row.values[class_id], field="CLASTEXT.CLASSID", maximum=0xFF),
                class_text_kit_id=_parse_uint(row.values[kit_id], field="CLASTEXT.KITID"),
                lower_name_strref=_parse_strref(row.values[lower_name]),
                description_strref=_parse_strref(row.values[description]),
                mixed_name_strref=_parse_strref(row.values[mixed_name]),
                biography_strref=_parse_strref(row.values[biography]),
                fallen=bool(fallen),
                brief_description_strref=_parse_strref(row.values[brief_description]),
                fallen_notice_strref=_parse_strref(row.values[fallen_notice]),
            )
        )
    return rows


def _project_kitlist(table: TwoDaTable) -> list[_RawKit]:
    (
        row_name,
        lower_name,
        mixed_name,
        help_text,
        abilities,
        proficiency,
        unusable,
        class_id,
        kit_ids,
    ) = _require_columns(table, _KITLIST_COLUMNS)
    kits: list[_RawKit] = []
    for row in table.rows:
        kit_ids_value = _parse_optional_uint(row.values[kit_ids], field="KITLIST.KITIDS")
        kits.append(
            _RawKit(
                source_resource=table.source_resource,
                ordinal=row.ordinal,
                row_id=_parse_uint(row.row_name, field="KITLIST row ID"),
                row_name=row.values[row_name],
                lower_name_strref=_parse_strref(row.values[lower_name]),
                mixed_name_strref=_parse_strref(row.values[mixed_name]),
                help_strref=_parse_strref(row.values[help_text]),
                abilities=_target_resref(row.values[abilities]),
                proficiency=_parse_optional_uint(
                    row.values[proficiency], field="KITLIST.PROFICIENCY"
                ),
                unusable=_parse_optional_uint(row.values[unusable], field="KITLIST.UNUSABLE"),
                class_id=_parse_optional_uint(
                    row.values[class_id], field="KITLIST.CLASS", maximum=0xFF
                ),
                kit_ids_value=kit_ids_value,
                class_text_kit_id=(
                    int(class_text_kit_id_from_kit_ids(kit_ids_value))
                    if kit_ids_value is not None
                    else None
                ),
            )
        )
    return kits


def _project_banter_links(table: TwoDaTable) -> list[CharacterResourceLink]:
    columns = [("FILE", _required_column(table, "FILE"))]
    index = _optional_column(table, "25FILE")
    if index is not None:
        columns.append(("25FILE", index))
    links: list[CharacterResourceLink] = []
    for row in table.rows:
        for column, index in columns:
            target_resref = _target_resref(row.values[index])
            if target_resref is not None:
                links.append(
                    CharacterResourceLink(
                        source_resource=table.source_resource,
                        ordinal=row.ordinal,
                        death_variable=row.row_name,
                        source_column=column,
                        role=CharacterResourceRole.BANTER_DIALOGUE,
                        target_type=ResourceTargetType.DIALOGUE,
                        target_resref=target_resref,
                    )
                )
    return links


def _project_party_dialogue_links(table: TwoDaTable) -> list[CharacterResourceLink]:
    fields = {
        "POST_DIALOG_FILE": (
            CharacterResourceRole.POST_DIALOGUE,
            ResourceTargetType.DIALOGUE,
        ),
        "JOIN_DIALOG_FILE": (
            CharacterResourceRole.JOIN_DIALOGUE,
            ResourceTargetType.DIALOGUE,
        ),
        "DREAM_SCRIPT_FILE": (
            CharacterResourceRole.DREAM_SCRIPT,
            ResourceTargetType.SCRIPT,
        ),
        "25POST_DIALOG_FILE": (
            CharacterResourceRole.POST_DIALOGUE,
            ResourceTargetType.DIALOGUE,
        ),
        "25JOIN_DIALOG_FILE": (
            CharacterResourceRole.JOIN_DIALOGUE,
            ResourceTargetType.DIALOGUE,
        ),
        "25DREAM_SCRIPT_FILE": (
            CharacterResourceRole.DREAM_SCRIPT,
            ResourceTargetType.SCRIPT,
        ),
        "25OVERRIDE_SCRIPT_FILE": (
            CharacterResourceRole.OVERRIDE_SCRIPT,
            ResourceTargetType.SCRIPT,
        ),
    }
    column_indices = dict(
        zip(
            _PARTY_DIALOGUE_COLUMNS,
            _require_columns(table, _PARTY_DIALOGUE_COLUMNS),
            strict=True,
        )
    )
    for column in _PARTY_DIALOGUE_OPTIONAL_COLUMNS:
        index = _optional_column(table, column)
        if index is not None:
            column_indices[column] = index
    links: list[CharacterResourceLink] = []
    for row in table.rows:
        for column, index in column_indices.items():
            role, target_type = fields[column]
            target_resref = _target_resref(row.values[index])
            if target_resref is not None:
                links.append(
                    CharacterResourceLink(
                        source_resource=table.source_resource,
                        ordinal=row.ordinal,
                        death_variable=row.row_name,
                        source_column=column,
                        role=role,
                        target_type=target_type,
                        target_resref=target_resref,
                    )
                )
    return links


def _project_interaction_rules(table: TwoDaTable) -> list[InteractionRule]:
    kinds = {
        "i": InteractionKind.INSULT,
        "c": InteractionKind.COMPLIMENT,
        "s": InteractionKind.SPECIAL,
    }
    rules: list[InteractionRule] = []
    for row in table.rows:
        for target_ordinal, (target_death_variable, value) in enumerate(
            zip(table.columns, row.values, strict=True)
        ):
            value = value.casefold()
            assert value == "0" or value in kinds, (
                f"{table.source_resource} row {row.row_name!r} has invalid interaction "
                f"value {value!r}"
            )
            if value != "0":
                rules.append(
                    InteractionRule(
                        source_resource=table.source_resource,
                        speaker_ordinal=row.ordinal,
                        target_ordinal=target_ordinal,
                        speaker_death_variable=row.row_name,
                        target_death_variable=target_death_variable,
                        kind=kinds[value],
                    )
                )
    return rules


def _project_soundset_lines(table: TwoDaTable) -> list[_RawSoundsetLine]:
    lines: list[_RawSoundsetLine] = []
    for row in table.rows:
        slot_id = SoundSlotId(_parse_uint(row.row_name, field="CHARSND slot", maximum=0xFF))
        for soundset_name, value in zip(table.columns, row.values, strict=True):
            strref = _parse_strref(value)
            if strref is not None:
                lines.append(
                    _RawSoundsetLine(
                        source_resource=table.source_resource,
                        soundset_name=soundset_name,
                        slot_id=slot_id,
                        strref=strref,
                    )
                )
    return lines


def _project_sound_slot_suffixes(table: TwoDaTable) -> list[SoundSlotSuffix]:
    (suffix,) = _require_columns(table, _CSOUND_COLUMNS)
    return [
        SoundSlotSuffix(
            source_resource=table.source_resource,
            ordinal=row.ordinal,
            slot_id=SoundSlotId(_parse_uint(row.row_name, field="CSOUND slot", maximum=0xFF)),
            file_suffix=_target_resref(row.values[suffix]),
        )
        for row in table.rows
    ]


def _project_sound_slot_groups(table: TwoDaTable) -> list[SoundSlotGroup]:
    offset_column, count_column = _require_columns(table, _SPEECH_COLUMNS)
    groups: list[SoundSlotGroup] = []
    for row in table.rows:
        offset = _parse_optional_uint(
            row.values[offset_column], field="SPEECH.OFFSET", maximum=0xFF
        )
        groups.append(
            SoundSlotGroup(
                source_resource=table.source_resource,
                ordinal=row.ordinal,
                row_name=row.row_name,
                offset=SoundSlotId(offset) if offset is not None else None,
                count=_parse_optional_uint(row.values[count_column], field="SPEECH.NUM"),
            )
        )
    return groups


def _project_favored_enemies(table: TwoDaTable) -> list[_RawFavoredEnemy]:
    name, race_id, help_text = _require_columns(table, _FAVORED_ENEMY_COLUMNS)
    return [
        _RawFavoredEnemy(
            source_resource=table.source_resource,
            ordinal=row.ordinal,
            row_name=row.row_name,
            name_strref=_parse_uint(row.values[name], field="HATERACE.STRREF"),
            race_id=_parse_uint(row.values[race_id], field="HATERACE.IDS", maximum=0xFF),
            help_strref=_parse_uint(row.values[help_text], field="HATERACE.STRREF_HELP"),
        )
        for row in table.rows
    ]


def _project_happiness_rules(table: TwoDaTable) -> list[HappinessRule]:
    columns = _require_columns(table, _HAPPINESS_COLUMNS)
    alignments = (
        HappinessAlignment.GOOD,
        HappinessAlignment.NEUTRAL,
        HappinessAlignment.EVIL,
    )
    return [
        HappinessRule(
            source_resource=table.source_resource,
            reputation=int(row.row_name),
            alignment=alignment,
            happiness=_parse_int(row.values[column]),
        )
        for row in table.rows
        for alignment, column in zip(alignments, columns, strict=True)
    ]


def _project_banter_timing(table: TwoDaTable) -> BanterTimingSettings:
    (value_column,) = _require_columns(table, _BANTER_TIMING_COLUMNS)
    rows = _require_rows(table, _BANTER_TIMING_ROWS)
    values = {
        name: _parse_uint(row.values[value_column], field=f"BANTTIMG.{name}")
        for name, row in zip(_BANTER_TIMING_ROWS, rows, strict=True)
    }
    return BanterTimingSettings(
        source_resource=table.source_resource,
        frequency=values["FREQUENCY"],
        probability=values["PROBABILITY"],
        replay_delay=values["REPLAYDELAY"],
        special_probability=values["SPECIALPROBABILITY"],
    )


def _project_engine_strings(table: TwoDaTable) -> list[_RawEngineString]:
    (strref,) = _require_columns(table, _ENGINE_STRING_COLUMNS)
    return [
        _RawEngineString(
            source_resource=table.source_resource,
            ordinal=row.ordinal,
            key=row.row_name,
            strref=_parse_strref(row.values[strref]),
        )
        for row in table.rows
    ]


def _project_months(table: TwoDaTable) -> list[_RawMonth]:
    days_column, name = _require_columns(table, _MONTH_COLUMNS)
    months: list[_RawMonth] = []
    for row in table.rows:
        days = _parse_uint(row.values[days_column], field="MONTHS.DAYS")
        months.append(
            _RawMonth(
                source_resource=table.source_resource,
                ordinal=row.ordinal,
                month_id=_parse_uint(row.row_name, field="MONTHS row ID"),
                days=days,
                name_strref=_parse_uint(row.values[name], field="MONTHS.NAME"),
            )
        )
    return months


def _project_calendar(table: TwoDaTable) -> _RawCalendar:
    (value,) = _require_columns(table, _CALENDAR_COLUMNS)
    start_time, start_year, normal_format, special_format = _require_rows(
        table,
        (
            "STARTTIME",
            "STARTYEAR",
            "NORMALDAYMONTHFORMAT",
            "SPECIALDAYMONTHFORMAT",
        ),
    )
    return _RawCalendar(
        source_resource=table.source_resource,
        start_time=_parse_uint(start_time.values[value], field="YEARS.STARTTIME"),
        start_year=_parse_uint(start_year.values[value], field="YEARS.STARTYEAR"),
        normal_format_strref=_parse_uint(
            normal_format.values[value], field="YEARS.NORMALDAYMONTHFORMAT"
        ),
        special_format_strref=_parse_uint(
            special_format.values[value], field="YEARS.SPECIALDAYMONTHFORMAT"
        ),
    )


def _resolve_strings(
    client: MetadataIeCliClient,
    game_root: Path,
    strrefs: list[int],
    *,
    workers: int,
) -> dict[int, str | None]:
    if not strrefs:
        return {}

    def resolve(strref: int) -> tuple[int, str | None]:
        reference = client.resolve_string(game_root, strref)
        return strref, reference.text

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="iecli-tlk") as executor:
        return dict(executor.map(resolve, strrefs))


def _resolve_race_text(row: _RawRaceText, text: dict[int, str | None]) -> RaceTextRow:
    return RaceTextRow(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        row_name=row.row_name,
        race_id=RaceId(row.race_id),
        name_strref=row.name_strref,
        name=_resolved(row.name_strref, text),
        description_strref=row.description_strref,
        description=_resolved(row.description_strref, text),
        uppercase_name_strref=row.uppercase_name_strref,
        uppercase_name=_resolved(row.uppercase_name_strref, text),
        biography_strref=row.biography_strref,
        biography=_resolved(row.biography_strref, text),
    )


def _resolve_class_text(row: _RawClassText, text: dict[int, str | None]) -> ClassTextRow:
    return ClassTextRow(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        row_name=row.row_name,
        class_id=ClassId(row.class_id),
        class_text_kit_id=ClassTextKitId(row.class_text_kit_id),
        lower_name_strref=row.lower_name_strref,
        lower_name=_resolved(row.lower_name_strref, text),
        description_strref=row.description_strref,
        description=_resolved(row.description_strref, text),
        mixed_name_strref=row.mixed_name_strref,
        mixed_name=_resolved(row.mixed_name_strref, text),
        biography_strref=row.biography_strref,
        biography=_resolved(row.biography_strref, text),
        fallen=row.fallen,
        brief_description_strref=row.brief_description_strref,
        brief_description=_resolved(row.brief_description_strref, text),
        fallen_notice_strref=row.fallen_notice_strref,
        fallen_notice=_resolved(row.fallen_notice_strref, text),
    )


def _resolve_kit(row: _RawKit, text: dict[int, str | None]) -> KitDefinition:
    return KitDefinition(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        row_id=KitListRowId(row.row_id),
        row_name=row.row_name,
        lower_name_strref=row.lower_name_strref,
        lower_name=_resolved(row.lower_name_strref, text),
        mixed_name_strref=row.mixed_name_strref,
        mixed_name=_resolved(row.mixed_name_strref, text),
        help_strref=row.help_strref,
        help_text=_resolved(row.help_strref, text),
        abilities=row.abilities,
        proficiency=row.proficiency,
        unusable=row.unusable,
        class_id=ClassId(row.class_id) if row.class_id is not None else None,
        kit_ids_value=(KitIdsValue(row.kit_ids_value) if row.kit_ids_value is not None else None),
        class_text_kit_id=(
            ClassTextKitId(row.class_text_kit_id) if row.class_text_kit_id is not None else None
        ),
    )


def _resolve_soundset_line(
    row: _RawSoundsetLine,
    text: dict[int, str | None],
) -> SoundsetLine:
    return SoundsetLine(
        source_resource=row.source_resource,
        soundset_name=row.soundset_name,
        slot_id=row.slot_id,
        strref=row.strref,
        text=text[row.strref],
    )


def _resolve_favored_enemy(
    row: _RawFavoredEnemy,
    text: dict[int, str | None],
) -> FavoredEnemyDefinition:
    return FavoredEnemyDefinition(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        row_name=row.row_name,
        name_strref=row.name_strref,
        name=text[row.name_strref],
        race_id=RaceId(row.race_id),
        help_strref=row.help_strref,
        help_text=text[row.help_strref],
    )


def _resolve_engine_string(
    row: _RawEngineString,
    text: dict[int, str | None],
) -> EngineString:
    return EngineString(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        key=row.key,
        strref=row.strref,
        text=_resolved(row.strref, text),
    )


def _resolve_month(row: _RawMonth, text: dict[int, str | None]) -> MonthDefinition:
    return MonthDefinition(
        source_resource=row.source_resource,
        ordinal=row.ordinal,
        month_id=row.month_id,
        days=row.days,
        name_strref=row.name_strref,
        name=text[row.name_strref],
    )


def _resolve_calendar(
    row: _RawCalendar,
    text: dict[int, str | None],
) -> CampaignCalendarDefinition:
    return CampaignCalendarDefinition(
        source_resource=row.source_resource,
        start_time=row.start_time,
        start_year=row.start_year,
        normal_format_strref=row.normal_format_strref,
        normal_format=text[row.normal_format_strref],
        special_format_strref=row.special_format_strref,
        special_format=text[row.special_format_strref],
    )


def _metadata_strrefs(
    race_rows: Iterable[_RawRaceText],
    class_rows: Iterable[_RawClassText],
    kits: Iterable[_RawKit],
    soundset_lines: Iterable[_RawSoundsetLine],
    engine_strings: Iterable[_RawEngineString],
    months: Iterable[_RawMonth],
    calendars: Iterable[_RawCalendar],
    favored_enemies: Iterable[_RawFavoredEnemy],
) -> set[int]:
    references: set[int] = set()
    for row in race_rows:
        references.update(
            value
            for value in (
                row.name_strref,
                row.description_strref,
                row.uppercase_name_strref,
                row.biography_strref,
            )
            if value is not None
        )
    for row in class_rows:
        references.update(
            value
            for value in (
                row.lower_name_strref,
                row.description_strref,
                row.mixed_name_strref,
                row.biography_strref,
                row.brief_description_strref,
                row.fallen_notice_strref,
            )
            if value is not None
        )
    for row in kits:
        references.update(
            value
            for value in (row.lower_name_strref, row.mixed_name_strref, row.help_strref)
            if value is not None
        )
    references.update(row.strref for row in soundset_lines)
    references.update(row.strref for row in engine_strings if row.strref is not None)
    references.update(row.name_strref for row in months)
    for row in calendars:
        references.update((row.normal_format_strref, row.special_format_strref))
    for row in favored_enemies:
        references.update((row.name_strref, row.help_strref))
    return references


def _ordered_bound_resources(
    bindings: Iterable[CampaignResourceBinding],
    kind: CampaignResourceKind,
) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for binding in bindings:
        resource = binding.resource_resref
        if binding.resource_kind is kind and resource is not None:
            key = resource.casefold()
        else:
            continue
        if key not in seen:
            seen.add(key)
            result.append(resource)
    return result


def _require_columns(table: TwoDaTable, required: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(_required_column(table, column) for column in required)


def _required_column(table: TwoDaTable, column: str) -> int:
    matches = [
        index
        for index, candidate in enumerate(table.columns)
        if candidate.casefold() == column.casefold()
    ]
    assert matches, f"{table.source_resource} is missing required column {column!r}"
    assert len(matches) == 1, f"{table.source_resource} repeats required column {column!r}"
    return matches[0]


def _optional_column(table: TwoDaTable, column: str) -> int | None:
    matches = [
        index
        for index, candidate in enumerate(table.columns)
        if candidate.casefold() == column.casefold()
    ]
    assert len(matches) <= 1, f"{table.source_resource} repeats optional column {column!r}"
    return matches[0] if matches else None


def _require_rows(table: TwoDaTable, required: tuple[str, ...]) -> tuple[TwoDaRow, ...]:
    rows: list[TwoDaRow] = []
    for row_name in required:
        matches = [row for row in table.rows if row.row_name.casefold() == row_name.casefold()]
        assert matches, f"{table.source_resource} is missing required row {row_name!r}"
        assert len(matches) == 1, f"{table.source_resource} repeats required row {row_name!r}"
        rows.append(matches[0])
    return tuple(rows)


def _tokens(line: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _TOKEN.finditer(line):
        token = match.group(1) if match.group(1) is not None else match.group(2)
        assert token is not None
        tokens.append(token)
    return tuple(tokens)


def _parse_strref(value: str) -> int | None:
    if value == "-1" or _is_all_asterisks(value):
        return None
    return _parse_uint(value, field="strref")


def _parse_optional_uint(
    value: str,
    *,
    field: str,
    maximum: int = 0xFFFF_FFFF,
) -> int | None:
    if value == "-1" or _is_all_asterisks(value):
        return None
    return _parse_uint(value, field=field, maximum=maximum)


def _parse_uint(value: str, *, field: str, maximum: int = 0xFFFF_FFFF) -> int:
    parsed = int(value, 0) if value.lower().startswith("0x") else int(value, 10)
    assert 0 <= parsed <= maximum, f"{field} is outside 0..{maximum}: {value!r}"
    return parsed


def _parse_int(value: str) -> int:
    return int(value, 0) if value.lower().startswith(("0x", "-0x")) else int(value, 10)


def _target_resref(value: str) -> str | None:
    if value.upper() == "NONE" or value in {"", "-1"} or _is_all_asterisks(value):
        return None
    return value


def _is_all_asterisks(value: str) -> bool:
    return bool(value) and set(value) == {"*"}


def _resolved(strref: int | None, text: dict[int, str | None]) -> str | None:
    return None if strref is None else text[strref]
