import datetime

from google.api import field_behavior_pb2 as _field_behavior_pb2
from google.api import resource_pb2 as _resource_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SourceKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SOURCE_KIND_UNSPECIFIED: _ClassVar[SourceKind]
    SOURCE_KIND_OVERRIDE: _ClassVar[SourceKind]
    SOURCE_KIND_BIF: _ClassVar[SourceKind]
    SOURCE_KIND_DLC: _ClassVar[SourceKind]

class DetailStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DETAIL_STATUS_UNSPECIFIED: _ClassVar[DetailStatus]
    DETAIL_STATUS_PENDING: _ClassVar[DetailStatus]
    DETAIL_STATUS_COMPLETE: _ClassVar[DetailStatus]
    DETAIL_STATUS_FAILED: _ClassVar[DetailStatus]

class AttributionStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ATTRIBUTION_STATUS_UNSPECIFIED: _ClassVar[AttributionStatus]
    ATTRIBUTION_STATUS_MATCHED: _ClassVar[AttributionStatus]
    ATTRIBUTION_STATUS_PARTIAL_MATCH: _ClassVar[AttributionStatus]
    ATTRIBUTION_STATUS_MISSING_DIALOGUE: _ClassVar[AttributionStatus]
    ATTRIBUTION_STATUS_NO_DIALOGUE: _ClassVar[AttributionStatus]
    ATTRIBUTION_STATUS_CHARACTER_UNAVAILABLE: _ClassVar[AttributionStatus]

class AttributionPublicationStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ATTRIBUTION_PUBLICATION_STATUS_UNSPECIFIED: _ClassVar[AttributionPublicationStatus]
    ATTRIBUTION_PUBLICATION_STATUS_MISSING: _ClassVar[AttributionPublicationStatus]
    ATTRIBUTION_PUBLICATION_STATUS_STALE: _ClassVar[AttributionPublicationStatus]
    ATTRIBUTION_PUBLICATION_STATUS_PUBLISHED: _ClassVar[AttributionPublicationStatus]

class DialogueLineKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DIALOGUE_LINE_KIND_UNSPECIFIED: _ClassVar[DialogueLineKind]
    DIALOGUE_LINE_KIND_NPC: _ClassVar[DialogueLineKind]
    DIALOGUE_LINE_KIND_PLAYER: _ClassVar[DialogueLineKind]
    DIALOGUE_LINE_KIND_JOURNAL: _ClassVar[DialogueLineKind]

class IdentifierKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    IDENTIFIER_KIND_UNSPECIFIED: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_RACE: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_CLASS: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_GENDER: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_ALIGNMENT: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_ENEMY_ALLY: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_GENERAL: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_SPECIFIC: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_ANIMATION: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_KIT: _ClassVar[IdentifierKind]
    IDENTIFIER_KIND_SOUND_SLOT: _ClassVar[IdentifierKind]

class RunKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUN_KIND_UNSPECIFIED: _ClassVar[RunKind]
    RUN_KIND_CHARACTERS: _ClassVar[RunKind]
    RUN_KIND_DIALOGUES: _ClassVar[RunKind]
    RUN_KIND_PORTRAITS: _ClassVar[RunKind]
    RUN_KIND_METADATA: _ClassVar[RunKind]
    RUN_KIND_ATTRIBUTION: _ClassVar[RunKind]

class RunStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUN_STATUS_UNSPECIFIED: _ClassVar[RunStatus]
    RUN_STATUS_RUNNING: _ClassVar[RunStatus]
    RUN_STATUS_COMPLETE: _ClassVar[RunStatus]
    RUN_STATUS_COMPLETE_WITH_ERRORS: _ClassVar[RunStatus]
    RUN_STATUS_FAILED: _ClassVar[RunStatus]
SOURCE_KIND_UNSPECIFIED: SourceKind
SOURCE_KIND_OVERRIDE: SourceKind
SOURCE_KIND_BIF: SourceKind
SOURCE_KIND_DLC: SourceKind
DETAIL_STATUS_UNSPECIFIED: DetailStatus
DETAIL_STATUS_PENDING: DetailStatus
DETAIL_STATUS_COMPLETE: DetailStatus
DETAIL_STATUS_FAILED: DetailStatus
ATTRIBUTION_STATUS_UNSPECIFIED: AttributionStatus
ATTRIBUTION_STATUS_MATCHED: AttributionStatus
ATTRIBUTION_STATUS_PARTIAL_MATCH: AttributionStatus
ATTRIBUTION_STATUS_MISSING_DIALOGUE: AttributionStatus
ATTRIBUTION_STATUS_NO_DIALOGUE: AttributionStatus
ATTRIBUTION_STATUS_CHARACTER_UNAVAILABLE: AttributionStatus
ATTRIBUTION_PUBLICATION_STATUS_UNSPECIFIED: AttributionPublicationStatus
ATTRIBUTION_PUBLICATION_STATUS_MISSING: AttributionPublicationStatus
ATTRIBUTION_PUBLICATION_STATUS_STALE: AttributionPublicationStatus
ATTRIBUTION_PUBLICATION_STATUS_PUBLISHED: AttributionPublicationStatus
DIALOGUE_LINE_KIND_UNSPECIFIED: DialogueLineKind
DIALOGUE_LINE_KIND_NPC: DialogueLineKind
DIALOGUE_LINE_KIND_PLAYER: DialogueLineKind
DIALOGUE_LINE_KIND_JOURNAL: DialogueLineKind
IDENTIFIER_KIND_UNSPECIFIED: IdentifierKind
IDENTIFIER_KIND_RACE: IdentifierKind
IDENTIFIER_KIND_CLASS: IdentifierKind
IDENTIFIER_KIND_GENDER: IdentifierKind
IDENTIFIER_KIND_ALIGNMENT: IdentifierKind
IDENTIFIER_KIND_ENEMY_ALLY: IdentifierKind
IDENTIFIER_KIND_GENERAL: IdentifierKind
IDENTIFIER_KIND_SPECIFIC: IdentifierKind
IDENTIFIER_KIND_ANIMATION: IdentifierKind
IDENTIFIER_KIND_KIT: IdentifierKind
IDENTIFIER_KIND_SOUND_SLOT: IdentifierKind
RUN_KIND_UNSPECIFIED: RunKind
RUN_KIND_CHARACTERS: RunKind
RUN_KIND_DIALOGUES: RunKind
RUN_KIND_PORTRAITS: RunKind
RUN_KIND_METADATA: RunKind
RUN_KIND_ATTRIBUTION: RunKind
RUN_STATUS_UNSPECIFIED: RunStatus
RUN_STATUS_RUNNING: RunStatus
RUN_STATUS_COMPLETE: RunStatus
RUN_STATUS_COMPLETE_WITH_ERRORS: RunStatus
RUN_STATUS_FAILED: RunStatus

class ResourceSource(_message.Message):
    __slots__ = ("kind", "path")
    KIND_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    kind: SourceKind
    path: str
    def __init__(self, kind: _Optional[_Union[SourceKind, str]] = ..., path: _Optional[str] = ...) -> None: ...

class ExtractionState(_message.Message):
    __slots__ = ("status", "error", "updated_at", "extraction_run")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    EXTRACTION_RUN_FIELD_NUMBER: _ClassVar[int]
    status: DetailStatus
    error: str
    updated_at: _timestamp_pb2.Timestamp
    extraction_run: str
    def __init__(self, status: _Optional[_Union[DetailStatus, str]] = ..., error: _Optional[str] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., extraction_run: _Optional[str] = ...) -> None: ...

class PipelineSummary(_message.Message):
    __slots__ = ("voices", "characters", "dialogues", "dialogue_lines", "character_sounds", "dialogue_transitions", "races", "character_classes", "kits", "identifier_definitions", "matched_characters", "partially_matched_characters", "missing_dialogue_characters", "unattributed_dialogues", "unattributed_dialogue_lines", "generated_voices", "directed_lines", "generated_audios", "running_tts_batches", "failed_tts_batches")
    VOICES_FIELD_NUMBER: _ClassVar[int]
    CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    DIALOGUES_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_LINES_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_SOUNDS_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_TRANSITIONS_FIELD_NUMBER: _ClassVar[int]
    RACES_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_CLASSES_FIELD_NUMBER: _ClassVar[int]
    KITS_FIELD_NUMBER: _ClassVar[int]
    IDENTIFIER_DEFINITIONS_FIELD_NUMBER: _ClassVar[int]
    MATCHED_CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    PARTIALLY_MATCHED_CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    MISSING_DIALOGUE_CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    UNATTRIBUTED_DIALOGUES_FIELD_NUMBER: _ClassVar[int]
    UNATTRIBUTED_DIALOGUE_LINES_FIELD_NUMBER: _ClassVar[int]
    GENERATED_VOICES_FIELD_NUMBER: _ClassVar[int]
    DIRECTED_LINES_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AUDIOS_FIELD_NUMBER: _ClassVar[int]
    RUNNING_TTS_BATCHES_FIELD_NUMBER: _ClassVar[int]
    FAILED_TTS_BATCHES_FIELD_NUMBER: _ClassVar[int]
    voices: int
    characters: int
    dialogues: int
    dialogue_lines: int
    character_sounds: int
    dialogue_transitions: int
    races: int
    character_classes: int
    kits: int
    identifier_definitions: int
    matched_characters: int
    partially_matched_characters: int
    missing_dialogue_characters: int
    unattributed_dialogues: int
    unattributed_dialogue_lines: int
    generated_voices: int
    directed_lines: int
    generated_audios: int
    running_tts_batches: int
    failed_tts_batches: int
    def __init__(self, voices: _Optional[int] = ..., characters: _Optional[int] = ..., dialogues: _Optional[int] = ..., dialogue_lines: _Optional[int] = ..., character_sounds: _Optional[int] = ..., dialogue_transitions: _Optional[int] = ..., races: _Optional[int] = ..., character_classes: _Optional[int] = ..., kits: _Optional[int] = ..., identifier_definitions: _Optional[int] = ..., matched_characters: _Optional[int] = ..., partially_matched_characters: _Optional[int] = ..., missing_dialogue_characters: _Optional[int] = ..., unattributed_dialogues: _Optional[int] = ..., unattributed_dialogue_lines: _Optional[int] = ..., generated_voices: _Optional[int] = ..., directed_lines: _Optional[int] = ..., generated_audios: _Optional[int] = ..., running_tts_batches: _Optional[int] = ..., failed_tts_batches: _Optional[int] = ...) -> None: ...

class Installation(_message.Message):
    __slots__ = ("name", "display_name", "database_path", "database_size", "attribution_publication", "attribution_completed_at", "summary")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    DATABASE_PATH_FIELD_NUMBER: _ClassVar[int]
    DATABASE_SIZE_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTION_PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTION_COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    name: str
    display_name: str
    database_path: str
    database_size: int
    attribution_publication: AttributionPublicationStatus
    attribution_completed_at: _timestamp_pb2.Timestamp
    summary: PipelineSummary
    def __init__(self, name: _Optional[str] = ..., display_name: _Optional[str] = ..., database_path: _Optional[str] = ..., database_size: _Optional[int] = ..., attribution_publication: _Optional[_Union[AttributionPublicationStatus, str]] = ..., attribution_completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., summary: _Optional[_Union[PipelineSummary, _Mapping]] = ...) -> None: ...

class CharacterReference(_message.Message):
    __slots__ = ("name", "engine_resource_name", "npc_line_count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RESOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    NPC_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    engine_resource_name: str
    npc_line_count: int
    def __init__(self, name: _Optional[str] = ..., engine_resource_name: _Optional[str] = ..., npc_line_count: _Optional[int] = ...) -> None: ...

class DialogueReference(_message.Message):
    __slots__ = ("name", "engine_resource_name", "npc_line_count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RESOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    NPC_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    engine_resource_name: str
    npc_line_count: int
    def __init__(self, name: _Optional[str] = ..., engine_resource_name: _Optional[str] = ..., npc_line_count: _Optional[int] = ...) -> None: ...

class GeneratedVoice(_message.Message):
    __slots__ = ("description", "language_code", "inworld_voice_id", "created_at")
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_CODE_FIELD_NUMBER: _ClassVar[int]
    INWORLD_VOICE_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    description: str
    language_code: str
    inworld_voice_id: str
    created_at: _timestamp_pb2.Timestamp
    def __init__(self, description: _Optional[str] = ..., language_code: _Optional[str] = ..., inworld_voice_id: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class CharacterDirection(_message.Message):
    __slots__ = ("directed_dialogue",)
    DIRECTED_DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    directed_dialogue: str
    def __init__(self, directed_dialogue: _Optional[str] = ...) -> None: ...

class NarratorDirection(_message.Message):
    __slots__ = ("directed_dialogue",)
    DIRECTED_DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    directed_dialogue: str
    def __init__(self, directed_dialogue: _Optional[str] = ...) -> None: ...

class DirectedLine(_message.Message):
    __slots__ = ("id", "voice", "voice_display_name", "character", "narrator", "audio_url")
    ID_FIELD_NUMBER: _ClassVar[int]
    VOICE_FIELD_NUMBER: _ClassVar[int]
    VOICE_DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_FIELD_NUMBER: _ClassVar[int]
    NARRATOR_FIELD_NUMBER: _ClassVar[int]
    AUDIO_URL_FIELD_NUMBER: _ClassVar[int]
    id: str
    voice: str
    voice_display_name: str
    character: CharacterDirection
    narrator: NarratorDirection
    audio_url: str
    def __init__(self, id: _Optional[str] = ..., voice: _Optional[str] = ..., voice_display_name: _Optional[str] = ..., character: _Optional[_Union[CharacterDirection, _Mapping]] = ..., narrator: _Optional[_Union[NarratorDirection, _Mapping]] = ..., audio_url: _Optional[str] = ...) -> None: ...

class Voice(_message.Message):
    __slots__ = ("name", "display_name", "prompt", "characters", "dialogues", "portrait", "npc_line_count", "serialized_size", "biography", "generated_voice", "directed_line_count", "generated_audio_count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    DIALOGUES_FIELD_NUMBER: _ClassVar[int]
    PORTRAIT_FIELD_NUMBER: _ClassVar[int]
    NPC_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_FIELD_NUMBER: _ClassVar[int]
    GENERATED_VOICE_FIELD_NUMBER: _ClassVar[int]
    DIRECTED_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AUDIO_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    display_name: str
    prompt: str
    characters: _containers.RepeatedCompositeFieldContainer[CharacterReference]
    dialogues: _containers.RepeatedCompositeFieldContainer[DialogueReference]
    portrait: str
    npc_line_count: int
    serialized_size: int
    biography: str
    generated_voice: GeneratedVoice
    directed_line_count: int
    generated_audio_count: int
    def __init__(self, name: _Optional[str] = ..., display_name: _Optional[str] = ..., prompt: _Optional[str] = ..., characters: _Optional[_Iterable[_Union[CharacterReference, _Mapping]]] = ..., dialogues: _Optional[_Iterable[_Union[DialogueReference, _Mapping]]] = ..., portrait: _Optional[str] = ..., npc_line_count: _Optional[int] = ..., serialized_size: _Optional[int] = ..., biography: _Optional[str] = ..., generated_voice: _Optional[_Union[GeneratedVoice, _Mapping]] = ..., directed_line_count: _Optional[int] = ..., generated_audio_count: _Optional[int] = ...) -> None: ...

class CharacterDialogueSummary(_message.Message):
    __slots__ = ("declared_dialogue_count", "resolved_dialogue_count", "dialogue_line_count", "npc_line_count", "player_line_count", "journal_line_count", "state_count", "transition_count", "serialized_size")
    DECLARED_DIALOGUE_COUNT_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_DIALOGUE_COUNT_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    NPC_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    JOURNAL_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    STATE_COUNT_FIELD_NUMBER: _ClassVar[int]
    TRANSITION_COUNT_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    declared_dialogue_count: int
    resolved_dialogue_count: int
    dialogue_line_count: int
    npc_line_count: int
    player_line_count: int
    journal_line_count: int
    state_count: int
    transition_count: int
    serialized_size: int
    def __init__(self, declared_dialogue_count: _Optional[int] = ..., resolved_dialogue_count: _Optional[int] = ..., dialogue_line_count: _Optional[int] = ..., npc_line_count: _Optional[int] = ..., player_line_count: _Optional[int] = ..., journal_line_count: _Optional[int] = ..., state_count: _Optional[int] = ..., transition_count: _Optional[int] = ..., serialized_size: _Optional[int] = ...) -> None: ...

class CharacterClassLevels(_message.Message):
    __slots__ = ("first_class", "second_class", "third_class")
    FIRST_CLASS_FIELD_NUMBER: _ClassVar[int]
    SECOND_CLASS_FIELD_NUMBER: _ClassVar[int]
    THIRD_CLASS_FIELD_NUMBER: _ClassVar[int]
    first_class: int
    second_class: int
    third_class: int
    def __init__(self, first_class: _Optional[int] = ..., second_class: _Optional[int] = ..., third_class: _Optional[int] = ...) -> None: ...

class CharacterBaseAttributes(_message.Message):
    __slots__ = ("strength", "strength_bonus", "intelligence", "wisdom", "dexterity", "constitution", "charisma")
    STRENGTH_FIELD_NUMBER: _ClassVar[int]
    STRENGTH_BONUS_FIELD_NUMBER: _ClassVar[int]
    INTELLIGENCE_FIELD_NUMBER: _ClassVar[int]
    WISDOM_FIELD_NUMBER: _ClassVar[int]
    DEXTERITY_FIELD_NUMBER: _ClassVar[int]
    CONSTITUTION_FIELD_NUMBER: _ClassVar[int]
    CHARISMA_FIELD_NUMBER: _ClassVar[int]
    strength: int
    strength_bonus: int
    intelligence: int
    wisdom: int
    dexterity: int
    constitution: int
    charisma: int
    def __init__(self, strength: _Optional[int] = ..., strength_bonus: _Optional[int] = ..., intelligence: _Optional[int] = ..., wisdom: _Optional[int] = ..., dexterity: _Optional[int] = ..., constitution: _Optional[int] = ..., charisma: _Optional[int] = ...) -> None: ...

class CharacterDetail(_message.Message):
    __slots__ = ("short_name", "short_name_strref", "long_name", "long_name_strref", "death_variable", "dialog_resref", "gender_id", "gender_label", "race_id", "race_label", "race", "class_id", "class_label", "character_class", "alignment_id", "alignment_label", "enemy_ally_id", "enemy_ally_label", "general_id", "general_label", "specific_id", "specific_label", "animation_id", "animation_label", "racial_enemy_id", "racial_enemy_label", "cre_kit_value", "kit_ids_value", "kit_label", "class_levels", "base_attributes", "morale", "morale_break", "morale_recovery_time", "reputation", "override_script", "class_script", "race_script", "general_script", "default_script", "small_portrait_resref", "large_portrait_resref", "cre_version")
    SHORT_NAME_FIELD_NUMBER: _ClassVar[int]
    SHORT_NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    LONG_NAME_FIELD_NUMBER: _ClassVar[int]
    LONG_NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    DEATH_VARIABLE_FIELD_NUMBER: _ClassVar[int]
    DIALOG_RESREF_FIELD_NUMBER: _ClassVar[int]
    GENDER_ID_FIELD_NUMBER: _ClassVar[int]
    GENDER_LABEL_FIELD_NUMBER: _ClassVar[int]
    RACE_ID_FIELD_NUMBER: _ClassVar[int]
    RACE_LABEL_FIELD_NUMBER: _ClassVar[int]
    RACE_FIELD_NUMBER: _ClassVar[int]
    CLASS_ID_FIELD_NUMBER: _ClassVar[int]
    CLASS_LABEL_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_CLASS_FIELD_NUMBER: _ClassVar[int]
    ALIGNMENT_ID_FIELD_NUMBER: _ClassVar[int]
    ALIGNMENT_LABEL_FIELD_NUMBER: _ClassVar[int]
    ENEMY_ALLY_ID_FIELD_NUMBER: _ClassVar[int]
    ENEMY_ALLY_LABEL_FIELD_NUMBER: _ClassVar[int]
    GENERAL_ID_FIELD_NUMBER: _ClassVar[int]
    GENERAL_LABEL_FIELD_NUMBER: _ClassVar[int]
    SPECIFIC_ID_FIELD_NUMBER: _ClassVar[int]
    SPECIFIC_LABEL_FIELD_NUMBER: _ClassVar[int]
    ANIMATION_ID_FIELD_NUMBER: _ClassVar[int]
    ANIMATION_LABEL_FIELD_NUMBER: _ClassVar[int]
    RACIAL_ENEMY_ID_FIELD_NUMBER: _ClassVar[int]
    RACIAL_ENEMY_LABEL_FIELD_NUMBER: _ClassVar[int]
    CRE_KIT_VALUE_FIELD_NUMBER: _ClassVar[int]
    KIT_IDS_VALUE_FIELD_NUMBER: _ClassVar[int]
    KIT_LABEL_FIELD_NUMBER: _ClassVar[int]
    CLASS_LEVELS_FIELD_NUMBER: _ClassVar[int]
    BASE_ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    MORALE_FIELD_NUMBER: _ClassVar[int]
    MORALE_BREAK_FIELD_NUMBER: _ClassVar[int]
    MORALE_RECOVERY_TIME_FIELD_NUMBER: _ClassVar[int]
    REPUTATION_FIELD_NUMBER: _ClassVar[int]
    OVERRIDE_SCRIPT_FIELD_NUMBER: _ClassVar[int]
    CLASS_SCRIPT_FIELD_NUMBER: _ClassVar[int]
    RACE_SCRIPT_FIELD_NUMBER: _ClassVar[int]
    GENERAL_SCRIPT_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_SCRIPT_FIELD_NUMBER: _ClassVar[int]
    SMALL_PORTRAIT_RESREF_FIELD_NUMBER: _ClassVar[int]
    LARGE_PORTRAIT_RESREF_FIELD_NUMBER: _ClassVar[int]
    CRE_VERSION_FIELD_NUMBER: _ClassVar[int]
    short_name: str
    short_name_strref: int
    long_name: str
    long_name_strref: int
    death_variable: str
    dialog_resref: str
    gender_id: int
    gender_label: str
    race_id: int
    race_label: str
    race: str
    class_id: int
    class_label: str
    character_class: str
    alignment_id: int
    alignment_label: str
    enemy_ally_id: int
    enemy_ally_label: str
    general_id: int
    general_label: str
    specific_id: int
    specific_label: str
    animation_id: int
    animation_label: str
    racial_enemy_id: int
    racial_enemy_label: str
    cre_kit_value: int
    kit_ids_value: int
    kit_label: str
    class_levels: CharacterClassLevels
    base_attributes: CharacterBaseAttributes
    morale: int
    morale_break: int
    morale_recovery_time: int
    reputation: int
    override_script: str
    class_script: str
    race_script: str
    general_script: str
    default_script: str
    small_portrait_resref: str
    large_portrait_resref: str
    cre_version: str
    def __init__(self, short_name: _Optional[str] = ..., short_name_strref: _Optional[int] = ..., long_name: _Optional[str] = ..., long_name_strref: _Optional[int] = ..., death_variable: _Optional[str] = ..., dialog_resref: _Optional[str] = ..., gender_id: _Optional[int] = ..., gender_label: _Optional[str] = ..., race_id: _Optional[int] = ..., race_label: _Optional[str] = ..., race: _Optional[str] = ..., class_id: _Optional[int] = ..., class_label: _Optional[str] = ..., character_class: _Optional[str] = ..., alignment_id: _Optional[int] = ..., alignment_label: _Optional[str] = ..., enemy_ally_id: _Optional[int] = ..., enemy_ally_label: _Optional[str] = ..., general_id: _Optional[int] = ..., general_label: _Optional[str] = ..., specific_id: _Optional[int] = ..., specific_label: _Optional[str] = ..., animation_id: _Optional[int] = ..., animation_label: _Optional[str] = ..., racial_enemy_id: _Optional[int] = ..., racial_enemy_label: _Optional[str] = ..., cre_kit_value: _Optional[int] = ..., kit_ids_value: _Optional[int] = ..., kit_label: _Optional[str] = ..., class_levels: _Optional[_Union[CharacterClassLevels, _Mapping]] = ..., base_attributes: _Optional[_Union[CharacterBaseAttributes, _Mapping]] = ..., morale: _Optional[int] = ..., morale_break: _Optional[int] = ..., morale_recovery_time: _Optional[int] = ..., reputation: _Optional[int] = ..., override_script: _Optional[str] = ..., class_script: _Optional[str] = ..., race_script: _Optional[str] = ..., general_script: _Optional[str] = ..., default_script: _Optional[str] = ..., small_portrait_resref: _Optional[str] = ..., large_portrait_resref: _Optional[str] = ..., cre_version: _Optional[str] = ...) -> None: ...

class Character(_message.Message):
    __slots__ = ("name", "engine_resource_name", "resref", "display_name", "voice", "portrait", "source", "extraction", "attribution_status", "serialized_size", "dialogue", "detail", "direct_dialogue", "biography")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RESOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    RESREF_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    VOICE_FIELD_NUMBER: _ClassVar[int]
    PORTRAIT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    EXTRACTION_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTION_STATUS_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    DIRECT_DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_FIELD_NUMBER: _ClassVar[int]
    name: str
    engine_resource_name: str
    resref: str
    display_name: str
    voice: str
    portrait: str
    source: ResourceSource
    extraction: ExtractionState
    attribution_status: AttributionStatus
    serialized_size: int
    dialogue: CharacterDialogueSummary
    detail: CharacterDetail
    direct_dialogue: str
    biography: str
    def __init__(self, name: _Optional[str] = ..., engine_resource_name: _Optional[str] = ..., resref: _Optional[str] = ..., display_name: _Optional[str] = ..., voice: _Optional[str] = ..., portrait: _Optional[str] = ..., source: _Optional[_Union[ResourceSource, _Mapping]] = ..., extraction: _Optional[_Union[ExtractionState, _Mapping]] = ..., attribution_status: _Optional[_Union[AttributionStatus, str]] = ..., serialized_size: _Optional[int] = ..., dialogue: _Optional[_Union[CharacterDialogueSummary, _Mapping]] = ..., detail: _Optional[_Union[CharacterDetail, _Mapping]] = ..., direct_dialogue: _Optional[str] = ..., biography: _Optional[str] = ...) -> None: ...

class DialogueDetail(_message.Message):
    __slots__ = ("dlg_version", "state_count", "transition_count", "npc_line_count", "player_line_count", "journal_line_count", "dialogue_line_count")
    DLG_VERSION_FIELD_NUMBER: _ClassVar[int]
    STATE_COUNT_FIELD_NUMBER: _ClassVar[int]
    TRANSITION_COUNT_FIELD_NUMBER: _ClassVar[int]
    NPC_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    JOURNAL_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    dlg_version: str
    state_count: int
    transition_count: int
    npc_line_count: int
    player_line_count: int
    journal_line_count: int
    dialogue_line_count: int
    def __init__(self, dlg_version: _Optional[str] = ..., state_count: _Optional[int] = ..., transition_count: _Optional[int] = ..., npc_line_count: _Optional[int] = ..., player_line_count: _Optional[int] = ..., journal_line_count: _Optional[int] = ..., dialogue_line_count: _Optional[int] = ...) -> None: ...

class Dialogue(_message.Message):
    __slots__ = ("name", "engine_resource_name", "resref", "source", "extraction", "serialized_size", "character_count", "detail", "directed_line_count", "generated_audio_count")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ENGINE_RESOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    RESREF_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    EXTRACTION_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_COUNT_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    DIRECTED_LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AUDIO_COUNT_FIELD_NUMBER: _ClassVar[int]
    name: str
    engine_resource_name: str
    resref: str
    source: ResourceSource
    extraction: ExtractionState
    serialized_size: int
    character_count: int
    detail: DialogueDetail
    directed_line_count: int
    generated_audio_count: int
    def __init__(self, name: _Optional[str] = ..., engine_resource_name: _Optional[str] = ..., resref: _Optional[str] = ..., source: _Optional[_Union[ResourceSource, _Mapping]] = ..., extraction: _Optional[_Union[ExtractionState, _Mapping]] = ..., serialized_size: _Optional[int] = ..., character_count: _Optional[int] = ..., detail: _Optional[_Union[DialogueDetail, _Mapping]] = ..., directed_line_count: _Optional[int] = ..., generated_audio_count: _Optional[int] = ...) -> None: ...

class DialogueLine(_message.Message):
    __slots__ = ("name", "dialogue", "dialogue_resref", "source_kind", "line_kind", "state_index", "state_trigger_index", "state_trigger_text", "transition_index", "strref", "text", "tokens", "serialized_size", "character_count", "directions")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_RESREF_FIELD_NUMBER: _ClassVar[int]
    SOURCE_KIND_FIELD_NUMBER: _ClassVar[int]
    LINE_KIND_FIELD_NUMBER: _ClassVar[int]
    STATE_INDEX_FIELD_NUMBER: _ClassVar[int]
    STATE_TRIGGER_INDEX_FIELD_NUMBER: _ClassVar[int]
    STATE_TRIGGER_TEXT_FIELD_NUMBER: _ClassVar[int]
    TRANSITION_INDEX_FIELD_NUMBER: _ClassVar[int]
    STRREF_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TOKENS_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_COUNT_FIELD_NUMBER: _ClassVar[int]
    DIRECTIONS_FIELD_NUMBER: _ClassVar[int]
    name: str
    dialogue: str
    dialogue_resref: str
    source_kind: SourceKind
    line_kind: DialogueLineKind
    state_index: int
    state_trigger_index: int
    state_trigger_text: str
    transition_index: int
    strref: int
    text: str
    tokens: _containers.RepeatedScalarFieldContainer[str]
    serialized_size: int
    character_count: int
    directions: _containers.RepeatedCompositeFieldContainer[DirectedLine]
    def __init__(self, name: _Optional[str] = ..., dialogue: _Optional[str] = ..., dialogue_resref: _Optional[str] = ..., source_kind: _Optional[_Union[SourceKind, str]] = ..., line_kind: _Optional[_Union[DialogueLineKind, str]] = ..., state_index: _Optional[int] = ..., state_trigger_index: _Optional[int] = ..., state_trigger_text: _Optional[str] = ..., transition_index: _Optional[int] = ..., strref: _Optional[int] = ..., text: _Optional[str] = ..., tokens: _Optional[_Iterable[str]] = ..., serialized_size: _Optional[int] = ..., character_count: _Optional[int] = ..., directions: _Optional[_Iterable[_Union[DirectedLine, _Mapping]]] = ...) -> None: ...

class CharacterSound(_message.Message):
    __slots__ = ("name", "character", "character_display_name", "slot_id", "slot_symbols", "slot_groups", "strref", "text", "serialized_size")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    SLOT_ID_FIELD_NUMBER: _ClassVar[int]
    SLOT_SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    SLOT_GROUPS_FIELD_NUMBER: _ClassVar[int]
    STRREF_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    name: str
    character: str
    character_display_name: str
    slot_id: int
    slot_symbols: _containers.RepeatedScalarFieldContainer[str]
    slot_groups: _containers.RepeatedScalarFieldContainer[str]
    strref: int
    text: str
    serialized_size: int
    def __init__(self, name: _Optional[str] = ..., character: _Optional[str] = ..., character_display_name: _Optional[str] = ..., slot_id: _Optional[int] = ..., slot_symbols: _Optional[_Iterable[str]] = ..., slot_groups: _Optional[_Iterable[str]] = ..., strref: _Optional[int] = ..., text: _Optional[str] = ..., serialized_size: _Optional[int] = ...) -> None: ...

class DialogueTransition(_message.Message):
    __slots__ = ("name", "dialogue", "dialogue_resref", "source_kind", "state_index", "transition_index", "flags_raw", "flags_decoded", "trigger_index", "trigger_text", "action_index", "action_text", "next_dialogue_resref", "next_state_index", "terminates_dialogue", "serialized_size", "next_dialogue")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    DIALOGUE_RESREF_FIELD_NUMBER: _ClassVar[int]
    SOURCE_KIND_FIELD_NUMBER: _ClassVar[int]
    STATE_INDEX_FIELD_NUMBER: _ClassVar[int]
    TRANSITION_INDEX_FIELD_NUMBER: _ClassVar[int]
    FLAGS_RAW_FIELD_NUMBER: _ClassVar[int]
    FLAGS_DECODED_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_INDEX_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_TEXT_FIELD_NUMBER: _ClassVar[int]
    ACTION_INDEX_FIELD_NUMBER: _ClassVar[int]
    ACTION_TEXT_FIELD_NUMBER: _ClassVar[int]
    NEXT_DIALOGUE_RESREF_FIELD_NUMBER: _ClassVar[int]
    NEXT_STATE_INDEX_FIELD_NUMBER: _ClassVar[int]
    TERMINATES_DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    SERIALIZED_SIZE_FIELD_NUMBER: _ClassVar[int]
    NEXT_DIALOGUE_FIELD_NUMBER: _ClassVar[int]
    name: str
    dialogue: str
    dialogue_resref: str
    source_kind: SourceKind
    state_index: int
    transition_index: int
    flags_raw: int
    flags_decoded: _containers.RepeatedScalarFieldContainer[str]
    trigger_index: int
    trigger_text: str
    action_index: int
    action_text: str
    next_dialogue_resref: str
    next_state_index: int
    terminates_dialogue: bool
    serialized_size: int
    next_dialogue: str
    def __init__(self, name: _Optional[str] = ..., dialogue: _Optional[str] = ..., dialogue_resref: _Optional[str] = ..., source_kind: _Optional[_Union[SourceKind, str]] = ..., state_index: _Optional[int] = ..., transition_index: _Optional[int] = ..., flags_raw: _Optional[int] = ..., flags_decoded: _Optional[_Iterable[str]] = ..., trigger_index: _Optional[int] = ..., trigger_text: _Optional[str] = ..., action_index: _Optional[int] = ..., action_text: _Optional[str] = ..., next_dialogue_resref: _Optional[str] = ..., next_state_index: _Optional[int] = ..., terminates_dialogue: _Optional[bool] = ..., serialized_size: _Optional[int] = ..., next_dialogue: _Optional[str] = ...) -> None: ...

class RaceText(_message.Message):
    __slots__ = ("source_resource", "campaigns", "row_name", "name_strref", "display_name", "description_strref", "description", "uppercase_name_strref", "uppercase_name", "biography_strref", "biography")
    SOURCE_RESOURCE_FIELD_NUMBER: _ClassVar[int]
    CAMPAIGNS_FIELD_NUMBER: _ClassVar[int]
    ROW_NAME_FIELD_NUMBER: _ClassVar[int]
    NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_STRREF_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    UPPERCASE_NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    UPPERCASE_NAME_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_STRREF_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_FIELD_NUMBER: _ClassVar[int]
    source_resource: str
    campaigns: _containers.RepeatedScalarFieldContainer[str]
    row_name: str
    name_strref: int
    display_name: str
    description_strref: int
    description: str
    uppercase_name_strref: int
    uppercase_name: str
    biography_strref: int
    biography: str
    def __init__(self, source_resource: _Optional[str] = ..., campaigns: _Optional[_Iterable[str]] = ..., row_name: _Optional[str] = ..., name_strref: _Optional[int] = ..., display_name: _Optional[str] = ..., description_strref: _Optional[int] = ..., description: _Optional[str] = ..., uppercase_name_strref: _Optional[int] = ..., uppercase_name: _Optional[str] = ..., biography_strref: _Optional[int] = ..., biography: _Optional[str] = ...) -> None: ...

class Race(_message.Message):
    __slots__ = ("name", "race_id", "symbols", "display_name", "texts")
    NAME_FIELD_NUMBER: _ClassVar[int]
    RACE_ID_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    TEXTS_FIELD_NUMBER: _ClassVar[int]
    name: str
    race_id: int
    symbols: _containers.RepeatedScalarFieldContainer[str]
    display_name: str
    texts: _containers.RepeatedCompositeFieldContainer[RaceText]
    def __init__(self, name: _Optional[str] = ..., race_id: _Optional[int] = ..., symbols: _Optional[_Iterable[str]] = ..., display_name: _Optional[str] = ..., texts: _Optional[_Iterable[_Union[RaceText, _Mapping]]] = ...) -> None: ...

class CharacterClassText(_message.Message):
    __slots__ = ("source_resource", "campaigns", "row_name", "class_text_kit_id", "lower_name_strref", "lower_name", "description_strref", "description", "mixed_name_strref", "mixed_name", "biography_strref", "biography", "fallen", "brief_description_strref", "brief_description", "fallen_notice_strref", "fallen_notice")
    SOURCE_RESOURCE_FIELD_NUMBER: _ClassVar[int]
    CAMPAIGNS_FIELD_NUMBER: _ClassVar[int]
    ROW_NAME_FIELD_NUMBER: _ClassVar[int]
    CLASS_TEXT_KIT_ID_FIELD_NUMBER: _ClassVar[int]
    LOWER_NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    LOWER_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_STRREF_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    MIXED_NAME_STRREF_FIELD_NUMBER: _ClassVar[int]
    MIXED_NAME_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_STRREF_FIELD_NUMBER: _ClassVar[int]
    BIOGRAPHY_FIELD_NUMBER: _ClassVar[int]
    FALLEN_FIELD_NUMBER: _ClassVar[int]
    BRIEF_DESCRIPTION_STRREF_FIELD_NUMBER: _ClassVar[int]
    BRIEF_DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    FALLEN_NOTICE_STRREF_FIELD_NUMBER: _ClassVar[int]
    FALLEN_NOTICE_FIELD_NUMBER: _ClassVar[int]
    source_resource: str
    campaigns: _containers.RepeatedScalarFieldContainer[str]
    row_name: str
    class_text_kit_id: int
    lower_name_strref: int
    lower_name: str
    description_strref: int
    description: str
    mixed_name_strref: int
    mixed_name: str
    biography_strref: int
    biography: str
    fallen: bool
    brief_description_strref: int
    brief_description: str
    fallen_notice_strref: int
    fallen_notice: str
    def __init__(self, source_resource: _Optional[str] = ..., campaigns: _Optional[_Iterable[str]] = ..., row_name: _Optional[str] = ..., class_text_kit_id: _Optional[int] = ..., lower_name_strref: _Optional[int] = ..., lower_name: _Optional[str] = ..., description_strref: _Optional[int] = ..., description: _Optional[str] = ..., mixed_name_strref: _Optional[int] = ..., mixed_name: _Optional[str] = ..., biography_strref: _Optional[int] = ..., biography: _Optional[str] = ..., fallen: _Optional[bool] = ..., brief_description_strref: _Optional[int] = ..., brief_description: _Optional[str] = ..., fallen_notice_strref: _Optional[int] = ..., fallen_notice: _Optional[str] = ...) -> None: ...

class CharacterClass(_message.Message):
    __slots__ = ("name", "class_id", "symbols", "display_name", "texts")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CLASS_ID_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    TEXTS_FIELD_NUMBER: _ClassVar[int]
    name: str
    class_id: int
    symbols: _containers.RepeatedScalarFieldContainer[str]
    display_name: str
    texts: _containers.RepeatedCompositeFieldContainer[CharacterClassText]
    def __init__(self, name: _Optional[str] = ..., class_id: _Optional[int] = ..., symbols: _Optional[_Iterable[str]] = ..., display_name: _Optional[str] = ..., texts: _Optional[_Iterable[_Union[CharacterClassText, _Mapping]]] = ...) -> None: ...

class Kit(_message.Message):
    __slots__ = ("name", "row_id", "row_name", "source_resource", "lower_name", "mixed_name", "display_name", "help_text", "character_class", "class_symbols", "kit_ids_value", "kit_symbols", "abilities_resref", "proficiency_column", "unusable_mask")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ROW_ID_FIELD_NUMBER: _ClassVar[int]
    ROW_NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_RESOURCE_FIELD_NUMBER: _ClassVar[int]
    LOWER_NAME_FIELD_NUMBER: _ClassVar[int]
    MIXED_NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    HELP_TEXT_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_CLASS_FIELD_NUMBER: _ClassVar[int]
    CLASS_SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    KIT_IDS_VALUE_FIELD_NUMBER: _ClassVar[int]
    KIT_SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    ABILITIES_RESREF_FIELD_NUMBER: _ClassVar[int]
    PROFICIENCY_COLUMN_FIELD_NUMBER: _ClassVar[int]
    UNUSABLE_MASK_FIELD_NUMBER: _ClassVar[int]
    name: str
    row_id: int
    row_name: str
    source_resource: str
    lower_name: str
    mixed_name: str
    display_name: str
    help_text: str
    character_class: str
    class_symbols: _containers.RepeatedScalarFieldContainer[str]
    kit_ids_value: int
    kit_symbols: _containers.RepeatedScalarFieldContainer[str]
    abilities_resref: str
    proficiency_column: int
    unusable_mask: int
    def __init__(self, name: _Optional[str] = ..., row_id: _Optional[int] = ..., row_name: _Optional[str] = ..., source_resource: _Optional[str] = ..., lower_name: _Optional[str] = ..., mixed_name: _Optional[str] = ..., display_name: _Optional[str] = ..., help_text: _Optional[str] = ..., character_class: _Optional[str] = ..., class_symbols: _Optional[_Iterable[str]] = ..., kit_ids_value: _Optional[int] = ..., kit_symbols: _Optional[_Iterable[str]] = ..., abilities_resref: _Optional[str] = ..., proficiency_column: _Optional[int] = ..., unusable_mask: _Optional[int] = ...) -> None: ...

class IdentifierDefinition(_message.Message):
    __slots__ = ("name", "kind", "value", "symbols", "source_resource", "display_name")
    NAME_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_RESOURCE_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    kind: IdentifierKind
    value: int
    symbols: _containers.RepeatedScalarFieldContainer[str]
    source_resource: str
    display_name: str
    def __init__(self, name: _Optional[str] = ..., kind: _Optional[_Union[IdentifierKind, str]] = ..., value: _Optional[int] = ..., symbols: _Optional[_Iterable[str]] = ..., source_resource: _Optional[str] = ..., display_name: _Optional[str] = ...) -> None: ...

class ExtractionRun(_message.Message):
    __slots__ = ("name", "run_id", "run_kind", "started_at", "completed_at", "status", "resources_discovered", "details_attempted", "details_extracted", "failures", "error")
    NAME_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    RUN_KIND_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    RESOURCES_DISCOVERED_FIELD_NUMBER: _ClassVar[int]
    DETAILS_ATTEMPTED_FIELD_NUMBER: _ClassVar[int]
    DETAILS_EXTRACTED_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    name: str
    run_id: str
    run_kind: RunKind
    started_at: _timestamp_pb2.Timestamp
    completed_at: _timestamp_pb2.Timestamp
    status: RunStatus
    resources_discovered: int
    details_attempted: int
    details_extracted: int
    failures: int
    error: str
    def __init__(self, name: _Optional[str] = ..., run_id: _Optional[str] = ..., run_kind: _Optional[_Union[RunKind, str]] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., completed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., status: _Optional[_Union[RunStatus, str]] = ..., resources_discovered: _Optional[int] = ..., details_attempted: _Optional[int] = ..., details_extracted: _Optional[int] = ..., failures: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class GetInstallationRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListVoicesRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListVoicesResponse(_message.Message):
    __slots__ = ("voices", "next_page_token", "total_size")
    VOICES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    voices: _containers.RepeatedCompositeFieldContainer[Voice]
    next_page_token: str
    total_size: int
    def __init__(self, voices: _Optional[_Iterable[_Union[Voice, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class GetVoiceRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListCharactersRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListCharactersResponse(_message.Message):
    __slots__ = ("characters", "next_page_token", "total_size")
    CHARACTERS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    characters: _containers.RepeatedCompositeFieldContainer[Character]
    next_page_token: str
    total_size: int
    def __init__(self, characters: _Optional[_Iterable[_Union[Character, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class GetCharacterRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListDialoguesRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListDialoguesResponse(_message.Message):
    __slots__ = ("dialogues", "next_page_token", "total_size")
    DIALOGUES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    dialogues: _containers.RepeatedCompositeFieldContainer[Dialogue]
    next_page_token: str
    total_size: int
    def __init__(self, dialogues: _Optional[_Iterable[_Union[Dialogue, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class GetDialogueRequest(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ListDialogueLinesRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListDialogueLinesResponse(_message.Message):
    __slots__ = ("dialogue_lines", "next_page_token", "total_size")
    DIALOGUE_LINES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    dialogue_lines: _containers.RepeatedCompositeFieldContainer[DialogueLine]
    next_page_token: str
    total_size: int
    def __init__(self, dialogue_lines: _Optional[_Iterable[_Union[DialogueLine, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListCharacterSoundsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListCharacterSoundsResponse(_message.Message):
    __slots__ = ("character_sounds", "next_page_token", "total_size")
    CHARACTER_SOUNDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    character_sounds: _containers.RepeatedCompositeFieldContainer[CharacterSound]
    next_page_token: str
    total_size: int
    def __init__(self, character_sounds: _Optional[_Iterable[_Union[CharacterSound, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListDialogueTransitionsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListDialogueTransitionsResponse(_message.Message):
    __slots__ = ("dialogue_transitions", "next_page_token", "total_size")
    DIALOGUE_TRANSITIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    dialogue_transitions: _containers.RepeatedCompositeFieldContainer[DialogueTransition]
    next_page_token: str
    total_size: int
    def __init__(self, dialogue_transitions: _Optional[_Iterable[_Union[DialogueTransition, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListRacesRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListRacesResponse(_message.Message):
    __slots__ = ("races", "next_page_token", "total_size")
    RACES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    races: _containers.RepeatedCompositeFieldContainer[Race]
    next_page_token: str
    total_size: int
    def __init__(self, races: _Optional[_Iterable[_Union[Race, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListCharacterClassesRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListCharacterClassesResponse(_message.Message):
    __slots__ = ("character_classes", "next_page_token", "total_size")
    CHARACTER_CLASSES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    character_classes: _containers.RepeatedCompositeFieldContainer[CharacterClass]
    next_page_token: str
    total_size: int
    def __init__(self, character_classes: _Optional[_Iterable[_Union[CharacterClass, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListKitsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListKitsResponse(_message.Message):
    __slots__ = ("kits", "next_page_token", "total_size")
    KITS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    kits: _containers.RepeatedCompositeFieldContainer[Kit]
    next_page_token: str
    total_size: int
    def __init__(self, kits: _Optional[_Iterable[_Union[Kit, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListIdentifierDefinitionsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListIdentifierDefinitionsResponse(_message.Message):
    __slots__ = ("identifier_definitions", "next_page_token", "total_size")
    IDENTIFIER_DEFINITIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    identifier_definitions: _containers.RepeatedCompositeFieldContainer[IdentifierDefinition]
    next_page_token: str
    total_size: int
    def __init__(self, identifier_definitions: _Optional[_Iterable[_Union[IdentifierDefinition, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...

class ListExtractionRunsRequest(_message.Message):
    __slots__ = ("parent", "page_size", "page_token", "filter", "order_by")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    ORDER_BY_FIELD_NUMBER: _ClassVar[int]
    parent: str
    page_size: int
    page_token: str
    filter: str
    order_by: str
    def __init__(self, parent: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., filter: _Optional[str] = ..., order_by: _Optional[str] = ...) -> None: ...

class ListExtractionRunsResponse(_message.Message):
    __slots__ = ("extraction_runs", "next_page_token", "total_size")
    EXTRACTION_RUNS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SIZE_FIELD_NUMBER: _ClassVar[int]
    extraction_runs: _containers.RepeatedCompositeFieldContainer[ExtractionRun]
    next_page_token: str
    total_size: int
    def __init__(self, extraction_runs: _Optional[_Iterable[_Union[ExtractionRun, _Mapping]]] = ..., next_page_token: _Optional[str] = ..., total_size: _Optional[int] = ...) -> None: ...
