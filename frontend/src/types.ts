export type SourceKind = "override" | "bif" | "dlc";
export type DetailStatus = "pending" | "complete" | "failed";
export type AttributionStatus =
  | "matched"
  | "missing_dialogue"
  | "dialogue_failed"
  | "no_dialogue"
  | "character_unavailable";
type DialogueLineKind = "npc" | "player" | "journal";
type RunKind = "characters" | "dialogues";
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

interface CharacterRow {
  resource_name: string;
  display_name: string | null;
  resref: string;
  source_kind: SourceKind;
  dialog_resref: string | null;
  gender_id: number | null;
  race_id: number | null;
  class_id: number | null;
  detail_status: DetailStatus;
  detail_error: string | null;
  attribution_status: AttributionStatus | null;
  serialized_size: number | null;
  dialogue_status: DetailStatus | null;
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
  serialized_size: number;
  character_count: number;
}

export type DialogueLinePage = Page<DialogueLineRow, LineSort>;

export interface FacetValue {
  value: string | number;
  count: number;
}

export interface FilterOptions {
  source_kinds: FacetValue[];
  gender_ids: FacetValue[];
  race_ids: FacetValue[];
  class_ids: FacetValue[];
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
  race_id: number;
  class_id: number;
  alignment_id: number;
  enemy_ally_id: number;
  general_id: number;
  specific_id: number;
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
