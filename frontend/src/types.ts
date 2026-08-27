export type SourceKind = "override" | "bif" | "dlc";
export type DetailStatus = "pending" | "complete" | "failed";
export type AttributionStatus =
  | "matched"
  | "missing_dialogue"
  | "dialogue_failed"
  | "no_dialogue"
  | "character_unavailable";
type DialogueLineKind = "npc" | "player" | "journal";
type RunKind = "characters" | "dialogues" | "metadata";
type RunStatus =
  | "running"
  | "complete"
  | "complete_with_errors"
  | "failed";
export type SortDirection = "asc" | "desc";

type OptionalFilter<T extends string> = "" | T;
type BooleanFilter = OptionalFilter<"true" | "false">;

export interface PaginatedQuery<TSort extends string> {
  page: number;
  page_size: number;
  q: string;
  sort: "" | TSort;
  direction: SortDirection;
}

export interface Page<TItem, TSort extends string> {
  items: TItem[];
  page: number;
  page_size: number;
  total: number;
  page_count: number;
  sort: TSort | "relevance";
  direction: SortDirection;
}

type CharacterSort =
  | "resource_name"
  | "display_name"
  | "source_kind"
  | "serialized_size"
  | "dialogue_line_count"
  | "npc_line_count"
  | "player_line_count"
  | "dialogue_state_count"
  | "dialogue_transition_count"
  | "updated_at";

export interface CharacterQuery extends PaginatedQuery<CharacterSort> {
  status: OptionalFilter<DetailStatus>;
  source_kind: OptionalFilter<SourceKind>;
  has_dialog: BooleanFilter;
  gender_id: string;
  race_id: string;
  class_id: string;
  attribution_status: OptionalFilter<AttributionStatus>;
}

export interface CharacterRow {
  resource_name: string;
  display_name: string | null;
  resref: string;
  source_kind: SourceKind;
  dialog_resref: string | null;
  gender_id: number | null;
  gender_label: string | null;
  race_id: number | null;
  race_label: string | null;
  class_id: number | null;
  class_label: string | null;
  alignment_id: number | null;
  alignment_label: string | null;
  enemy_ally_id: number | null;
  enemy_ally_label: string | null;
  general_id: number | null;
  general_label: string | null;
  specific_id: number | null;
  specific_label: string | null;
  animation_id: number | null;
  animation_label: string | null;
  racial_enemy_id: number | null;
  racial_enemy_label: string | null;
  cre_kit_value: number | null;
  kit_ids_value: number | null;
  kit_label: string | null;
  first_class_level: number | null;
  second_class_level: number | null;
  third_class_level: number | null;
  detail_status: DetailStatus;
  detail_error: string | null;
  attribution_status: AttributionStatus | null;
  serialized_size: number | null;
  dialogue_status: DetailStatus | null;
  declared_dialogue_count: number | null;
  resolved_dialogue_count: number | null;
  dialogue_line_count: number | null;
  npc_line_count: number | null;
  player_line_count: number | null;
  journal_line_count: number | null;
  dialogue_state_count: number | null;
  dialogue_transition_count: number | null;
  dialogue_serialized_size: number | null;
  updated_at: string;
}

export type CharacterPage = Page<CharacterRow, CharacterSort>;

type DialogueSort =
  | "resource_name"
  | "source_kind"
  | "serialized_size"
  | "dialogue_line_count"
  | "npc_line_count"
  | "player_line_count"
  | "character_count"
  | "updated_at";

export interface DialogueQuery extends PaginatedQuery<DialogueSort> {
  status: OptionalFilter<DetailStatus>;
  source_kind: OptionalFilter<SourceKind>;
  attributed: BooleanFilter;
}

interface DialogueRow {
  resource_name: string;
  resref: string;
  source_kind: SourceKind;
  source_path: string;
  detail_status: DetailStatus;
  detail_error: string | null;
  serialized_size: number | null;
  dialogue_line_count: number | null;
  npc_line_count: number | null;
  player_line_count: number | null;
  journal_line_count: number | null;
  character_count: number;
  updated_at: string;
}

export type DialoguePage = Page<DialogueRow, DialogueSort>;

type LineSort =
  | "dialogue_resource_name"
  | "line_kind"
  | "strref"
  | "serialized_size"
  | "state_index"
  | "transition_index";

export interface LineQuery extends PaginatedQuery<LineSort> {
  line_kind: OptionalFilter<DialogueLineKind>;
  source_kind: OptionalFilter<SourceKind>;
  attributed: BooleanFilter;
}

interface DialogueLineRow {
  id: string;
  dialogue_resource_name: string;
  dialogue_resref: string;
  source_kind: SourceKind;
  line_kind: DialogueLineKind;
  state_index: number;
  transition_index: number | null;
  strref: number;
  text: string | null;
  tokens: string[];
  state_trigger_index: number | null;
  state_trigger_text: string | null;
  serialized_size: number;
  character_count: number;
}

export type DialogueLinePage = Page<DialogueLineRow, LineSort>;

export interface FacetValue {
  value: string | number;
  label: string | null;
  count: number;
}

export interface FilterOptions {
  source_kinds: FacetValue[];
  gender_ids: FacetValue[];
  race_ids: FacetValue[];
  class_ids: FacetValue[];
  metadata_class_ids: FacetValue[];
  sound_slot_ids: FacetValue[];
  campaigns: string[];
  identifier_kinds: SimpleIdentifierKind[];
}

interface ExtractionRunSummary {
  id: string;
  run_kind: RunKind;
  started_at: string;
  completed_at: string | null;
  status: RunStatus;
  resources_discovered: number;
  details_attempted: number;
  details_extracted: number;
  failures: number;
  error: string | null;
}

export interface PipelineStats {
  database_path: string;
  database_size: number;
  characters_total: number;
  characters_complete: number;
  characters_failed: number;
  characters_with_dialogue: number;
  characters_unavailable: number;
  characters_matched: number;
  characters_missing_dialogue: number;
  characters_dialogue_failed: number;
  characters_without_dialogue: number;
  dialogues_total: number;
  dialogues_complete: number;
  dialogue_lines: number;
  line_records_total: number;
  character_sounds_total: number;
  soundset_lines_total: number;
  transition_edges_total: number;
  character_resource_links_total: number;
  interaction_rules_total: number;
  engine_strings_total: number;
  sound_slot_groups_total: number;
  favored_enemies_total: number;
  happiness_rules_total: number;
  banter_timing_settings_total: number;
  races_total: number;
  classes_total: number;
  kits_total: number;
  identifiers_total: number;
  campaigns_total: number;
  dialogues_attributed: number;
  dialogues_unattributed: number;
  attributed_dialogue_lines: number;
  unattributed_dialogue_lines: number;
  attribution_completed_at: string | null;
  latest_runs: ExtractionRunSummary[];
}

interface CharacterDetail {
  resource_name: string;
  display_name: string;
  short_name: string | null;
  short_name_strref: number;
  long_name: string | null;
  long_name_strref: number;
  death_variable: string | null;
  dialog_resref: string | null;
  gender_id: number;
  gender_label: string;
  race_id: number;
  race_label: string;
  class_id: number;
  class_label: string;
  alignment_id: number;
  alignment_label: string;
  enemy_ally_id: number;
  enemy_ally_label: string;
  general_id: number;
  general_label: string;
  specific_id: number;
  specific_label: string;
  animation_id: number;
  animation_label: string;
  racial_enemy_id: number;
  racial_enemy_label: string;
  cre_kit_value: number;
  kit_ids_value: number | null;
  kit_label: string | null;
  first_class_level: number;
  second_class_level: number;
  third_class_level: number;
  strength: number;
  strength_bonus: number;
  intelligence: number;
  wisdom: number;
  dexterity: number;
  constitution: number;
  charisma: number;
  morale: number;
  morale_break: number;
  morale_recovery_time: number;
  reputation: number;
  override_script: string | null;
  class_script: string | null;
  race_script: string | null;
  general_script: string | null;
  default_script: string | null;
  small_portrait: string | null;
  large_portrait: string | null;
  cre_version: string;
}

interface DialogueDetail {
  resource_name: string;
  resref: string;
  dlg_version: string;
  state_count: number;
  transition_count: number;
  npc_line_count: number;
  player_line_count: number;
  journal_line_count: number;
  dialogue_line_count: number;
  pydantic_json_size: number;
}

export interface CharacterDetailResponse {
  character: CharacterDetail;
  dialogue: DialogueDetail | null;
  source_kind: SourceKind;
  source_path: string;
  character_serialized_size: number;
  dialogue_serialized_size: number | null;
  updated_at: string;
  attribution_status: AttributionStatus | null;
}

export type RaceSort = "race_id" | "row_name" | "name" | "source_resource";

export interface RaceQuery extends PaginatedQuery<RaceSort> {
  campaign: string;
}

export interface RaceRow {
  key: string;
  race_id: number;
  symbols: string[];
  source_resource: string | null;
  ordinal: number | null;
  campaigns: string[];
  row_name: string | null;
  name_strref: number | null;
  name: string | null;
  description_strref: number | null;
  description: string | null;
  uppercase_name_strref: number | null;
  uppercase_name: string | null;
  biography_strref: number | null;
  biography: string | null;
}

export type RacePage = Page<RaceRow, RaceSort>;

export type ClassSort = "class_id" | "row_name" | "lower_name" | "fallen";

export interface ClassQuery extends PaginatedQuery<ClassSort> {
  campaign: string;
  fallen: BooleanFilter;
  class_id: string;
}

export interface ClassRow {
  key: string;
  class_id: number;
  symbols: string[];
  source_resource: string | null;
  ordinal: number | null;
  campaigns: string[];
  row_name: string | null;
  class_text_kit_id: number | null;
  lower_name_strref: number | null;
  lower_name: string | null;
  description_strref: number | null;
  description: string | null;
  mixed_name_strref: number | null;
  mixed_name: string | null;
  biography_strref: number | null;
  biography: string | null;
  fallen: boolean | null;
  brief_description_strref: number | null;
  brief_description: string | null;
  fallen_notice_strref: number | null;
  fallen_notice: string | null;
}

export type ClassPage = Page<ClassRow, ClassSort>;

export type KitSort = "row_id" | "row_name" | "lower_name" | "class_id";

export interface KitQuery extends PaginatedQuery<KitSort> {
  class_id: string;
}

export interface KitRow {
  key: string;
  source_resource: string;
  ordinal: number;
  row_id: number;
  row_name: string;
  lower_name_strref: number | null;
  lower_name: string | null;
  mixed_name_strref: number | null;
  mixed_name: string | null;
  help_strref: number | null;
  help_text: string | null;
  abilities_resref: string | null;
  proficiency_column: number | null;
  unusable_mask: number | null;
  class_id: number | null;
  class_symbols: string[];
  kit_ids_value: number | null;
  kit_symbols: string[];
  class_text_kit_id: number | null;
}

export type KitPage = Page<KitRow, KitSort>;

export type IdentifierKind =
  | "race"
  | "class"
  | "gender"
  | "alignment"
  | "enemy_ally"
  | "general"
  | "specific"
  | "animation"
  | "kit"
  | "sound_slot";

export type SimpleIdentifierKind = Exclude<IdentifierKind, "race" | "class" | "kit">;

export type IdentifierSort = "kind" | "value" | "source_resource";

export interface IdentifierQuery extends PaginatedQuery<IdentifierSort> {
  kind: OptionalFilter<SimpleIdentifierKind>;
}

export interface IdentifierRow {
  key: string;
  kind: SimpleIdentifierKind;
  value: number;
  symbols: string[];
  source_resource: string;
}

export type IdentifierPage = Page<IdentifierRow, IdentifierSort>;

export type VoiceSort =
  | "character_resource_name"
  | "slot_id"
  | "strref"
  | "serialized_size";

export interface VoiceQuery extends PaginatedQuery<VoiceSort> {
  slot_id: string;
}

export interface VoiceRow {
  key: string;
  character_resource_name: string;
  character_name: string | null;
  slot_id: number;
  slot_symbols: string[];
  slot_groups: string[];
  strref: number;
  text: string | null;
  serialized_size: number;
}

export type VoicePage = Page<VoiceRow, VoiceSort>;

export type TransitionSort =
  | "location"
  | "dialogue_resource_name"
  | "state_index"
  | "transition_index"
  | "serialized_size";

export interface TransitionQuery extends PaginatedQuery<TransitionSort> {
  terminates_dialog: BooleanFilter;
}

export interface TransitionRow {
  id: string;
  dialogue_resource_name: string;
  dialogue_resref: string;
  source_kind: SourceKind;
  state_index: number;
  transition_index: number;
  flags_raw: number;
  flags_decoded: string[];
  trigger_index: number | null;
  trigger_text: string | null;
  action_index: number | null;
  action_text: string | null;
  next_dialog: string | null;
  next_state_index: number | null;
  terminates_dialog: boolean;
  serialized_size: number;
}

export type TransitionPage = Page<TransitionRow, TransitionSort>;
