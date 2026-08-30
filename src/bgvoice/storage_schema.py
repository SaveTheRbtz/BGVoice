"""LanceDB table names, record ownership, and indexes."""

from dataclasses import dataclass

from lancedb.index import FTS, BTree
from lancedb.pydantic import LanceModel

from bgvoice.storage_records import (
    BanterTimingSettingsRecord,
    CampaignCalendarRecord,
    CampaignDefinitionRecord,
    CampaignResourceBindingRecord,
    CharacterAttributionRecord,
    CharacterRecord,
    CharacterResourceLinkRecord,
    CharacterSoundRecord,
    ClassTextRecord,
    DialogueLineRecord,
    DialogueRecord,
    DialogueTransitionRecord,
    DirectedLineRecord,
    EngineStringRecord,
    ExtractionRunRecord,
    FavoredEnemyRecord,
    GeneratedAudioRecord,
    GenerationFailureRecord,
    HappinessRuleRecord,
    IdentifierDefinitionRecord,
    InteractionRuleRecord,
    KitDefinitionRecord,
    MonthDefinitionRecord,
    PortraitImageRecord,
    RaceTextRecord,
    ReadableItemRecord,
    SoundsetLineRecord,
    SoundSlotGroupRecord,
    SoundSlotSuffixRecord,
    TtsBatchRecord,
    VoiceGenerationRecord,
    VoiceProfileRecord,
    VoiceResourceRecord,
)

_CHARACTERS = "characters"
_PORTRAIT_IMAGES = "portrait_images"
_READABLE_ITEMS = "readable_items"
_CHARACTER_SOUNDS = "character_sounds"
_CHARACTER_DIALOGUES = "character_dialogues"
_VOICE_RESOURCES = "voice_resources"
_VOICE_PROFILES = "voice_profiles"
_VOICE_GENERATIONS = "voice_generations"
_DIRECTED_LINES = "directed_lines"
_GENERATED_AUDIO = "generated_audio"
_TTS_BATCHES = "tts_batches"
_GENERATION_FAILURES = "generation_failures"
_DIALOGUES = "dialogues"
_DIALOGUE_LINES = "dialogue_lines"
_DIALOGUE_TRANSITIONS = "dialogue_transitions"
_EXTRACTION_RUNS = "extraction_runs"
_IDENTIFIER_DEFINITIONS = "identifier_definitions"
_CAMPAIGNS = "campaigns"
_CAMPAIGN_RESOURCE_BINDINGS = "campaign_resource_bindings"
_CHARACTER_RESOURCE_LINKS = "character_resource_links"
_INTERACTION_RULES = "interaction_rules"
_SOUNDSET_LINES = "soundset_lines"
_SOUND_SLOT_SUFFIXES = "sound_slot_suffixes"
_SOUND_SLOT_GROUPS = "sound_slot_groups"
_FAVORED_ENEMIES = "favored_enemies"
_HAPPINESS_RULES = "happiness_rules"
_BANTER_TIMING_SETTINGS = "banter_timing_settings"
_ENGINE_STRINGS = "engine_strings"
_MONTHS = "months"
_CAMPAIGN_CALENDARS = "campaign_calendars"
_RACE_TEXTS = "race_texts"
_CLASS_TEXTS = "class_texts"
_KITS = "kits"
_METADATA_TABLES = (
    _IDENTIFIER_DEFINITIONS,
    _CAMPAIGNS,
    _CAMPAIGN_RESOURCE_BINDINGS,
    _CHARACTER_RESOURCE_LINKS,
    _INTERACTION_RULES,
    _SOUNDSET_LINES,
    _SOUND_SLOT_SUFFIXES,
    _SOUND_SLOT_GROUPS,
    _FAVORED_ENEMIES,
    _HAPPINESS_RULES,
    _BANTER_TIMING_SETTINGS,
    _ENGINE_STRINGS,
    _MONTHS,
    _CAMPAIGN_CALENDARS,
    _RACE_TEXTS,
    _CLASS_TEXTS,
    _KITS,
)
TABLE_NAMES = frozenset(
    {
        _CHARACTERS,
        _PORTRAIT_IMAGES,
        _READABLE_ITEMS,
        _CHARACTER_SOUNDS,
        _CHARACTER_DIALOGUES,
        _VOICE_RESOURCES,
        _VOICE_PROFILES,
        _VOICE_GENERATIONS,
        _DIRECTED_LINES,
        _GENERATED_AUDIO,
        _TTS_BATCHES,
        _GENERATION_FAILURES,
        _DIALOGUES,
        _DIALOGUE_LINES,
        _DIALOGUE_TRANSITIONS,
        _EXTRACTION_RUNS,
        *_METADATA_TABLES,
    }
)

_FTS = FTS(
    base_tokenizer="simple",
    language="English",
    with_position=True,
    max_token_length=64,
    lower_case=True,
    stem=True,
    remove_stop_words=False,
    ascii_folding=True,
)


@dataclass(frozen=True, slots=True)
class IndexSpec:
    column: str
    config: BTree | FTS
    name: str


TABLE_INDEXES: dict[str, tuple[IndexSpec, ...]] = {
    _CHARACTERS: (
        IndexSpec("resource_name", BTree(), "characters_resource_name_btree"),
        IndexSpec("search_text", _FTS, "characters_search_fts"),
    ),
    _PORTRAIT_IMAGES: (IndexSpec("resref", BTree(), "portrait_images_resref_btree"),),
    _READABLE_ITEMS: (
        IndexSpec("resource_name", BTree(), "readable_items_resource_name_btree"),
        IndexSpec("kind", BTree(), "readable_items_kind_btree"),
        IndexSpec("search_text", _FTS, "readable_items_search_fts"),
    ),
    _CHARACTER_SOUNDS: (
        IndexSpec("id", BTree(), "character_sounds_id_btree"),
        IndexSpec(
            "character_resource_name",
            BTree(),
            "character_sounds_character_btree",
        ),
        IndexSpec("slot_id", BTree(), "character_sounds_slot_btree"),
        IndexSpec("search_text", _FTS, "character_sounds_search_fts"),
    ),
    _CHARACTER_DIALOGUES: (
        IndexSpec("key", BTree(), "character_dialogues_key_btree"),
        IndexSpec("run_id", BTree(), "character_dialogues_run_btree"),
        IndexSpec(
            "character_resource_name",
            BTree(),
            "character_dialogues_character_btree",
        ),
    ),
    _VOICE_RESOURCES: (
        IndexSpec("key", BTree(), "voice_resources_key_btree"),
        IndexSpec("run_id", BTree(), "voice_resources_run_btree"),
        IndexSpec("voice_id", BTree(), "voice_resources_voice_id_btree"),
        IndexSpec("search_text", _FTS, "voice_resources_search_fts"),
    ),
    _VOICE_PROFILES: (
        IndexSpec("profile_id", BTree(), "voice_profiles_profile_id_btree"),
        IndexSpec("inworld_voice_id", BTree(), "voice_profiles_inworld_voice_id_btree"),
    ),
    _VOICE_GENERATIONS: (
        IndexSpec("voice_id", BTree(), "voice_generations_voice_id_btree"),
        IndexSpec("profile_id", BTree(), "voice_generations_profile_id_btree"),
    ),
    _DIRECTED_LINES: (
        IndexSpec("id", BTree(), "directed_lines_id_btree"),
        IndexSpec("voice_id", BTree(), "directed_lines_voice_id_btree"),
        IndexSpec("dialogue_line_id", BTree(), "directed_lines_dialogue_line_id_btree"),
    ),
    _GENERATED_AUDIO: (
        IndexSpec("id", BTree(), "generated_audio_id_btree"),
        IndexSpec("voice_id", BTree(), "generated_audio_voice_id_btree"),
        IndexSpec("dialogue_line_id", BTree(), "generated_audio_dialogue_line_id_btree"),
    ),
    _TTS_BATCHES: (IndexSpec("operation_name", BTree(), "tts_batches_operation_name_btree"),),
    _GENERATION_FAILURES: (
        IndexSpec("id", BTree(), "generation_failures_id_btree"),
        IndexSpec("stage", BTree(), "generation_failures_stage_btree"),
        IndexSpec("voice_id", BTree(), "generation_failures_voice_id_btree"),
    ),
    _DIALOGUES: (
        IndexSpec("resource_name", BTree(), "dialogues_resource_name_btree"),
        IndexSpec("search_text", _FTS, "dialogues_search_fts"),
    ),
    _DIALOGUE_LINES: (
        IndexSpec("id", BTree(), "dialogue_lines_id_btree"),
        IndexSpec(
            "dialogue_resource_name",
            BTree(),
            "dialogue_lines_dialogue_btree",
        ),
        IndexSpec("search_text", _FTS, "dialogue_lines_search_fts"),
    ),
    _DIALOGUE_TRANSITIONS: (
        IndexSpec("id", BTree(), "dialogue_transitions_id_btree"),
        IndexSpec(
            "dialogue_resource_name",
            BTree(),
            "dialogue_transitions_dialogue_btree",
        ),
        IndexSpec("next_dialog", BTree(), "dialogue_transitions_next_dialog_btree"),
        IndexSpec("search_text", _FTS, "dialogue_transitions_search_fts"),
    ),
    _EXTRACTION_RUNS: (),
    _IDENTIFIER_DEFINITIONS: (
        IndexSpec("key", BTree(), "identifier_definitions_key_btree"),
        IndexSpec("kind", BTree(), "identifier_definitions_kind_btree"),
        IndexSpec("value", BTree(), "identifier_definitions_value_btree"),
        IndexSpec("search_text", _FTS, "identifier_definitions_search_fts"),
    ),
    _CAMPAIGNS: (
        IndexSpec("key", BTree(), "campaigns_key_btree"),
        IndexSpec("campaign_id", BTree(), "campaigns_campaign_id_btree"),
    ),
    _CAMPAIGN_RESOURCE_BINDINGS: (
        IndexSpec("key", BTree(), "campaign_resource_bindings_key_btree"),
        IndexSpec("campaign_id", BTree(), "campaign_resource_bindings_campaign_btree"),
        IndexSpec(
            "resource_resref",
            BTree(),
            "campaign_resource_bindings_resource_btree",
        ),
    ),
    _CHARACTER_RESOURCE_LINKS: (
        IndexSpec("key", BTree(), "character_resource_links_key_btree"),
        IndexSpec(
            "death_variable",
            BTree(),
            "character_resource_links_death_variable_btree",
        ),
        IndexSpec(
            "target_resref",
            BTree(),
            "character_resource_links_target_btree",
        ),
        IndexSpec("search_text", _FTS, "character_resource_links_search_fts"),
    ),
    _INTERACTION_RULES: (
        IndexSpec("key", BTree(), "interaction_rules_key_btree"),
        IndexSpec(
            "speaker_death_variable",
            BTree(),
            "interaction_rules_speaker_btree",
        ),
        IndexSpec(
            "target_death_variable",
            BTree(),
            "interaction_rules_target_btree",
        ),
        IndexSpec("search_text", _FTS, "interaction_rules_search_fts"),
    ),
    _SOUNDSET_LINES: (
        IndexSpec("key", BTree(), "soundset_lines_key_btree"),
        IndexSpec("soundset_name", BTree(), "soundset_lines_soundset_btree"),
        IndexSpec("slot_id", BTree(), "soundset_lines_slot_btree"),
        IndexSpec("search_text", _FTS, "soundset_lines_search_fts"),
    ),
    _SOUND_SLOT_SUFFIXES: (
        IndexSpec("key", BTree(), "sound_slot_suffixes_key_btree"),
        IndexSpec("slot_id", BTree(), "sound_slot_suffixes_slot_btree"),
    ),
    _SOUND_SLOT_GROUPS: (
        IndexSpec("key", BTree(), "sound_slot_groups_key_btree"),
        IndexSpec("row_name", BTree(), "sound_slot_groups_row_name_btree"),
        IndexSpec("search_text", _FTS, "sound_slot_groups_search_fts"),
    ),
    _FAVORED_ENEMIES: (
        IndexSpec("key", BTree(), "favored_enemies_key_btree"),
        IndexSpec("race_id", BTree(), "favored_enemies_race_id_btree"),
        IndexSpec("search_text", _FTS, "favored_enemies_search_fts"),
    ),
    _HAPPINESS_RULES: (
        IndexSpec("key", BTree(), "happiness_rules_key_btree"),
        IndexSpec("reputation", BTree(), "happiness_rules_reputation_btree"),
        IndexSpec("alignment", BTree(), "happiness_rules_alignment_btree"),
    ),
    _BANTER_TIMING_SETTINGS: (IndexSpec("key", BTree(), "banter_timing_settings_key_btree"),),
    _ENGINE_STRINGS: (
        IndexSpec("key", BTree(), "engine_strings_key_btree"),
        IndexSpec("strref", BTree(), "engine_strings_strref_btree"),
        IndexSpec("search_text", _FTS, "engine_strings_search_fts"),
    ),
    _MONTHS: (
        IndexSpec("key", BTree(), "months_key_btree"),
        IndexSpec("month_id", BTree(), "months_month_id_btree"),
        IndexSpec("search_text", _FTS, "months_search_fts"),
    ),
    _CAMPAIGN_CALENDARS: (
        IndexSpec("key", BTree(), "campaign_calendars_key_btree"),
        IndexSpec("search_text", _FTS, "campaign_calendars_search_fts"),
    ),
    _RACE_TEXTS: (
        IndexSpec("key", BTree(), "race_texts_key_btree"),
        IndexSpec("race_id", BTree(), "race_texts_race_id_btree"),
        IndexSpec("source_resource", BTree(), "race_texts_source_resource_btree"),
        IndexSpec("search_text", _FTS, "race_texts_search_fts"),
    ),
    _CLASS_TEXTS: (
        IndexSpec("key", BTree(), "class_texts_key_btree"),
        IndexSpec("class_id", BTree(), "class_texts_class_id_btree"),
        IndexSpec("source_resource", BTree(), "class_texts_source_resource_btree"),
        IndexSpec("search_text", _FTS, "class_texts_search_fts"),
    ),
    _KITS: (
        IndexSpec("key", BTree(), "kits_key_btree"),
        IndexSpec("row_id", BTree(), "kits_row_id_btree"),
        IndexSpec("class_id", BTree(), "kits_class_id_btree"),
        IndexSpec("kit_ids_value", BTree(), "kits_kit_ids_value_btree"),
        IndexSpec("search_text", _FTS, "kits_search_fts"),
    ),
}

TABLE_MODELS: dict[str, type[LanceModel]] = {
    _CHARACTERS: CharacterRecord,
    _PORTRAIT_IMAGES: PortraitImageRecord,
    _READABLE_ITEMS: ReadableItemRecord,
    _CHARACTER_SOUNDS: CharacterSoundRecord,
    _CHARACTER_DIALOGUES: CharacterAttributionRecord,
    _VOICE_RESOURCES: VoiceResourceRecord,
    _VOICE_PROFILES: VoiceProfileRecord,
    _VOICE_GENERATIONS: VoiceGenerationRecord,
    _DIRECTED_LINES: DirectedLineRecord,
    _GENERATED_AUDIO: GeneratedAudioRecord,
    _TTS_BATCHES: TtsBatchRecord,
    _GENERATION_FAILURES: GenerationFailureRecord,
    _DIALOGUES: DialogueRecord,
    _DIALOGUE_LINES: DialogueLineRecord,
    _DIALOGUE_TRANSITIONS: DialogueTransitionRecord,
    _EXTRACTION_RUNS: ExtractionRunRecord,
    _IDENTIFIER_DEFINITIONS: IdentifierDefinitionRecord,
    _CAMPAIGNS: CampaignDefinitionRecord,
    _CAMPAIGN_RESOURCE_BINDINGS: CampaignResourceBindingRecord,
    _CHARACTER_RESOURCE_LINKS: CharacterResourceLinkRecord,
    _INTERACTION_RULES: InteractionRuleRecord,
    _SOUNDSET_LINES: SoundsetLineRecord,
    _SOUND_SLOT_SUFFIXES: SoundSlotSuffixRecord,
    _SOUND_SLOT_GROUPS: SoundSlotGroupRecord,
    _FAVORED_ENEMIES: FavoredEnemyRecord,
    _HAPPINESS_RULES: HappinessRuleRecord,
    _BANTER_TIMING_SETTINGS: BanterTimingSettingsRecord,
    _ENGINE_STRINGS: EngineStringRecord,
    _MONTHS: MonthDefinitionRecord,
    _CAMPAIGN_CALENDARS: CampaignCalendarRecord,
    _RACE_TEXTS: RaceTextRecord,
    _CLASS_TEXTS: ClassTextRecord,
    _KITS: KitDefinitionRecord,
}
