import { useCallback, useEffect, useRef, useState } from "react";

import {
  getCharacterDetail,
  getCharacters,
  getDialogues,
  getFilterOptions,
  getLines,
  getStats,
} from "./api";
import {
  BrowserHeading,
  ErrorBanner,
  FacetFilter,
  Pagination,
  RelevanceButton,
  ResultCount,
  SearchBox,
  SelectFilter,
  SortHeader,
} from "./browser";
import {
  browserTab,
  countFilters,
  errorMessage,
  navigateToTab,
  useBrowser,
} from "./browser-state";
import type { BrowserTab } from "./browser-state";
import { formatBytes, formatCount, formatDate, formatHex } from "./format";
import {
  ClassBrowser,
  IdentifierBrowser,
  KitBrowser,
  RaceBrowser,
} from "./MetadataBrowser";
import { TransitionBrowser, VoiceBrowser } from "./PipelineBrowsers";
import type {
  AttributionStatus,
  CharacterDetailResponse,
  CharacterQuery,
  DetailStatus,
  DialogueQuery,
  FilterOptions,
  LineQuery,
  PipelineStats,
  SourceKind,
} from "./types";

const DETAIL_STATUSES = ["complete", "pending", "failed"] as const satisfies readonly DetailStatus[];
const SOURCE_KINDS = ["override", "bif", "dlc"] as const satisfies readonly SourceKind[];
const ATTRIBUTION_STATUSES = [
  "matched",
  "missing_dialogue",
  "dialogue_failed",
  "no_dialogue",
  "character_unavailable",
] as const satisfies readonly AttributionStatus[];
const BOOLEAN_FILTERS = ["true", "false"] as const;
const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "summary",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

type DetailState =
  | {
      resourceName: string;
      status: "complete";
      value: CharacterDetailResponse;
    }
  | {
      resourceName: string;
      status: "failed";
      error: string;
    };

const DEFAULT_CHARACTER_QUERY: CharacterQuery = {
  page: 1,
  page_size: 25,
  q: "",
  status: "",
  source_kind: "",
  has_dialog: "",
  gender_id: "",
  race_id: "",
  class_id: "",
  attribution_status: "",
  sort: "",
  direction: "desc",
};

const DEFAULT_DIALOGUE_QUERY: DialogueQuery = {
  page: 1,
  page_size: 25,
  q: "",
  status: "",
  source_kind: "",
  attributed: "",
  sort: "",
  direction: "desc",
};

const DEFAULT_LINE_QUERY: LineQuery = {
  page: 1,
  page_size: 25,
  q: "",
  line_kind: "",
  source_kind: "",
  attributed: "",
  sort: "",
  direction: "desc",
};

export default function App() {
  const [activeTab, setActiveTab] = useState<BrowserTab>(browserTab);
  const [visitedTabs, setVisitedTabs] = useState<ReadonlySet<BrowserTab>>(
    () => new Set([browserTab()]),
  );
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<DetailState | null>(null);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const detail = detailState?.resourceName === selected && detailState.status === "complete"
    ? detailState.value
    : null;
  const detailError = detailState?.resourceName === selected && detailState.status === "failed"
    ? detailState.error
    : null;
  const closeDetail = useCallback(() => setSelected(null), []);
  const openDetail = useCallback((resourceName: string) => {
    setDetailState(null);
    setSelected(resourceName);
  }, []);
  const retryDetail = useCallback(() => {
    setDetailState(null);
    setDetailAttempt((current) => current + 1);
  }, []);
  const attributionNote = stats == null
    ? "Loading attribution stage…"
    : stats.attribution_completed_at == null
      ? "Attribution not run"
      : `Completed ${formatDate(stats.attribution_completed_at)}`;

  const openTab = useCallback((tab: BrowserTab) => {
    if (tab === activeTab) return;
    navigateToTab(tab);
    setActiveTab(tab);
    setVisitedTabs((current) => new Set(current).add(tab));
  }, [activeTab]);

  useEffect(() => {
    const restoreTab = () => {
      const tab = browserTab();
      setActiveTab(tab);
      setVisitedTabs((current) => new Set(current).add(tab));
    };
    window.addEventListener("popstate", restoreTab);
    return () => window.removeEventListener("popstate", restoreTab);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;

    async function refresh(): Promise<void> {
      try {
        const [nextStats, nextOptions] = await Promise.all([
          getStats(controller.signal),
          getFilterOptions(controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setStats(nextStats);
        setOptions(nextOptions);
        setRefreshError(null);
      } catch (reason: unknown) {
        if (!controller.signal.aborted) setRefreshError(errorMessage(reason));
      } finally {
        if (!controller.signal.aborted) {
          timer = window.setTimeout(() => {
            void refresh();
          }, 15_000);
        }
      }
    }

    void refresh();
    return () => {
      controller.abort();
      if (timer != null) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (selected == null) return undefined;
    const controller = new AbortController();
    getCharacterDetail(selected, controller.signal)
      .then((value) => {
        setDetailState({ resourceName: selected, status: "complete", value });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setDetailState({
            resourceName: selected,
            status: "failed",
            error: errorMessage(reason),
          });
        }
      });
    return () => controller.abort();
  }, [detailAttempt, selected]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">B</div>
          <div>
            <div className="brand">BGVOICE</div>
            <div className="subtitle">EET voice pipeline</div>
          </div>
        </div>
        <div className="read-only"><span /> READ ONLY</div>
      </header>

      <main>
        <section className="intro">
          <div>
            <p className="eyebrow">PIPELINE OBSERVATORY</p>
            <h1>Pipeline database</h1>
            <p>
              Inspect characters, dialogue resources, addressable lines, and
              resolved engine definitions without touching pipeline state.
            </p>
          </div>
          <div className="database-meta" title={stats?.database_path}>
            <span>DATABASE</span>
            <strong>{formatBytes(stats?.database_size)}</strong>
          </div>
        </section>

        <section className="stats-grid" aria-label="Pipeline summary">
          <Stat label="Characters" value={stats?.characters_total} note={`${formatCount(stats?.characters_complete)} complete`} />
          <Stat label="Matched CREs" value={stats?.characters_matched} note={`${formatCount(stats?.characters_missing_dialogue)} missing references`} />
          <Stat label="Unavailable CREs" value={stats?.characters_unavailable} note={attributionNote} />
          <Stat label="DLG inventory" value={stats?.dialogues_total} note={`${formatCount(stats?.dialogues_complete)} fully decoded`} />
          <Stat label="Unattributed DLGs" value={stats?.dialogues_unattributed} note={`${formatCount(stats?.unattributed_dialogue_lines)} unassigned lines`} />
          <Stat label="Dialogue lines" value={stats?.dialogue_lines} note="NPC + player responses" accent />
        </section>

        <section className="support-stats" aria-label="Imported support data">
          <SupportStat label="CRE voice slots" value={stats?.character_sounds_total} />
          <SupportStat label="Preset soundset lines" value={stats?.soundset_lines_total} />
          <SupportStat label="Transition edges" value={stats?.transition_edges_total} />
          <SupportStat label="Character / resource links" value={stats?.character_resource_links_total} />
          <SupportStat label="Interaction rules" value={stats?.interaction_rules_total} />
          <SupportStat label="Resolved engine strings" value={stats?.engine_strings_total} />
          <SupportStat label="Voice slot groups" value={stats?.sound_slot_groups_total} />
          <SupportStat label="Favored enemies" value={stats?.favored_enemies_total} />
          <SupportStat label="Happiness rules" value={stats?.happiness_rules_total} />
          <SupportStat label="Banter timing settings" value={stats?.banter_timing_settings_total} />
        </section>

        <nav className="view-tabs" role="tablist" aria-label="Pipeline data views">
          <Tab active={activeTab === "characters"} count={stats?.characters_total} label="Characters" onClick={() => openTab("characters")} />
          <Tab active={activeTab === "dialogues"} count={stats?.dialogues_total} label="Dialogues" onClick={() => openTab("dialogues")} />
          <Tab active={activeTab === "lines"} count={stats?.line_records_total} label="Lines" onClick={() => openTab("lines")} />
          <Tab active={activeTab === "voices"} count={stats?.character_sounds_total} label="Voices" onClick={() => openTab("voices")} />
          <Tab active={activeTab === "transitions"} count={stats?.transition_edges_total} label="Transitions" onClick={() => openTab("transitions")} />
          <Tab active={activeTab === "races"} count={stats?.races_total} label="Races" onClick={() => openTab("races")} />
          <Tab active={activeTab === "classes"} count={stats?.classes_total} label="Classes" onClick={() => openTab("classes")} />
          <Tab active={activeTab === "kits"} count={stats?.kits_total} label="Kits" onClick={() => openTab("kits")} />
          <Tab active={activeTab === "identifiers"} count={stats?.identifiers_total} label="Identifiers" onClick={() => openTab("identifiers")} />
        </nav>

        {refreshError != null && (
          <ErrorBanner message={refreshError} onDismiss={() => setRefreshError(null)} />
        )}
        {visitedTabs.has("characters") && (
          <div hidden={activeTab !== "characters"}>
            <CharacterBrowser active={activeTab === "characters"} options={options} onSelect={openDetail} />
          </div>
        )}
        {visitedTabs.has("dialogues") && (
          <div hidden={activeTab !== "dialogues"}>
            <DialogueBrowser active={activeTab === "dialogues"} />
          </div>
        )}
        {visitedTabs.has("lines") && (
          <div hidden={activeTab !== "lines"}>
            <LineBrowser active={activeTab === "lines"} />
          </div>
        )}
        {visitedTabs.has("voices") && (
          <div hidden={activeTab !== "voices"}>
            <VoiceBrowser active={activeTab === "voices"} soundSlots={options?.sound_slot_ids ?? []} />
          </div>
        )}
        {visitedTabs.has("transitions") && (
          <div hidden={activeTab !== "transitions"}>
            <TransitionBrowser active={activeTab === "transitions"} />
          </div>
        )}
        {visitedTabs.has("races") && (
          <div hidden={activeTab !== "races"}>
            <RaceBrowser active={activeTab === "races"} campaigns={options?.campaigns ?? []} />
          </div>
        )}
        {visitedTabs.has("classes") && (
          <div hidden={activeTab !== "classes"}>
            <ClassBrowser
              active={activeTab === "classes"}
              campaigns={options?.campaigns ?? []}
              classIds={options?.metadata_class_ids ?? []}
            />
          </div>
        )}
        {visitedTabs.has("kits") && (
          <div hidden={activeTab !== "kits"}>
            <KitBrowser active={activeTab === "kits"} classIds={options?.metadata_class_ids ?? []} />
          </div>
        )}
        {visitedTabs.has("identifiers") && (
          <div hidden={activeTab !== "identifiers"}>
            <IdentifierBrowser active={activeTab === "identifiers"} kinds={options?.identifier_kinds ?? []} />
          </div>
        )}

        <section className="runs-card">
          <div>
            <p className="eyebrow">RECENT ACTIVITY</p>
            <h2>Extraction runs</h2>
          </div>
          <div className="run-list">
            {stats?.latest_runs.map((run) => (
              <div className="run" key={run.id}>
                <span className={`run-dot status-${run.status}`} />
                <div>
                  <strong>{run.run_kind}</strong>
                  <span>Run #{run.id} · {formatDate(run.completed_at)}</span>
                </div>
                <div className="run-progress">
                  <strong>{formatCount(run.details_extracted)}</strong>
                  <span>of {formatCount(run.resources_discovered)}</span>
                </div>
                <span className={`status-pill status-${run.status}`}>
                  {run.status.replaceAll("_", " ")}
                </span>
              </div>
            ))}
          </div>
        </section>
      </main>

      {selected != null && (
        <DetailDrawer
          resourceName={selected}
          detail={detail}
          error={detailError}
          onClose={closeDetail}
          onRetry={retryDetail}
        />
      )}
    </div>
  );
}

function CharacterBrowser({
  active,
  options,
  onSelect,
}: {
  active: boolean;
  options: FilterOptions | null;
  onSelect: (resourceName: string) => void;
}) {
  const browser = useBrowser(
    "characters",
    active,
    DEFAULT_CHARACTER_QUERY,
    getCharacters,
  );
  const { query, page, loading } = browser;
  const activeFilters = countFilters(
    browser.search,
    query.status,
    query.source_kind,
    query.has_dialog,
    query.gender_id,
    query.race_id,
    query.class_id,
    query.attribution_status,
  );

  return (
    <section className="browser-card tab-panel">
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search names, resrefs, variables, scripts…"
          label="Full-text search characters"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.sort === ""}
          onClick={browser.sortByRelevance}
        />
        <ResultCount loading={loading} count={page.total} noun="results" />
      </div>

      <div className="filters" aria-label="Character filters">
        <SelectFilter label="Status" value={query.status} values={DETAIL_STATUSES} onChange={(value) => browser.update("status", value)} />
        <FacetFilter label="Source" value={query.source_kind} values={options?.source_kinds} onChange={(value) => browser.update("source_kind", value)} />
        <SelectFilter label="Direct CRE DLG" value={query.has_dialog} values={BOOLEAN_FILTERS} labels={{ true: "Has direct DLG", false: "No direct DLG" }} onChange={(value) => browser.update("has_dialog", value)} />
        <FacetFilter label="Gender ID" value={query.gender_id} values={options?.gender_ids} onChange={(value) => browser.update("gender_id", value)} />
        <FacetFilter label="Race ID" value={query.race_id} values={options?.race_ids} onChange={(value) => browser.update("race_id", value)} />
        <FacetFilter label="Class ID" value={query.class_id} values={options?.class_ids} onChange={(value) => browser.update("class_id", value)} />
        <SelectFilter
          label="Attribution"
          value={query.attribution_status}
          values={ATTRIBUTION_STATUSES}
          labels={{ matched: "Matched", missing_dialogue: "Missing DLG", dialogue_failed: "DLG failed", no_dialogue: "No DLG", character_unavailable: "Character unavailable" }}
          onChange={(value) => browser.update("attribution_status", value)}
        />
        {activeFilters > 0 && (
          <button className="clear-filters" type="button" onClick={browser.reset}>
            Clear {activeFilters}
          </button>
        )}
      </div>

      <div className={`table-wrap ${loading ? "is-loading" : ""}`}>
        <table>
          <thead>
            <tr>
              <SortHeader label="Character" sort="display_name" query={page} onSort={browser.sortBy} />
              <SortHeader label="Resource" sort="resource_name" query={page} onSort={browser.sortBy} />
              <SortHeader label="Source" sort="source_kind" query={page} onSort={browser.sortBy} />
              <th>Gender</th>
              <th>Race</th>
              <th>Class / kit</th>
              <th className="numeric">DLGs resolved / declared</th>
              <SortHeader label="Object size" sort="serialized_size" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Lines" sort="dialogue_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="NPC" sort="npc_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Player" sort="player_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="States" sort="dialogue_state_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Transitions" sort="dialogue_transition_count" query={page} onSort={browser.sortBy} numeric />
              <th>Status</th>
              <th aria-label="Open details" />
            </tr>
          </thead>
          <tbody>
            {page.items.map((character) => (
              <tr key={character.resource_name}>
                <td>
                  <button
                    className="character-link"
                    type="button"
                    onClick={() => onSelect(character.resource_name)}
                  >
                    <strong>{character.display_name ?? character.resref}</strong>
                    <span>Direct CRE DLG · {character.dialog_resref ?? "None"}</span>
                  </button>
                </td>
                <td className="mono">{character.resource_name}</td>
                <td><span className={`source source-${character.source_kind}`}>{character.source_kind}</span></td>
                <td><ResolvedValue label={character.gender_label} id={character.gender_id} /></td>
                <td><ResolvedValue label={character.race_label} id={character.race_id} /></td>
                <td>
                  <ResolvedValue label={character.class_label} id={character.class_id} />
                  {(character.kit_label != null || character.kit_ids_value != null) && (
                    <ResolvedValue label={character.kit_label} id={character.kit_ids_value} secondary />
                  )}
                </td>
                <td className="numeric">
                  <DialogueCoverage
                    resolved={character.resolved_dialogue_count}
                    declared={character.declared_dialogue_count}
                  />
                </td>
                <td className="numeric mono">{formatBytes(character.serialized_size)}</td>
                <td className="numeric emphatic">{formatCount(character.dialogue_line_count)}</td>
                <td className="numeric">{formatCount(character.npc_line_count)}</td>
                <td className="numeric">{formatCount(character.player_line_count)}</td>
                <td className="numeric">{formatCount(character.dialogue_state_count)}</td>
                <td className="numeric">{formatCount(character.dialogue_transition_count)}</td>
                <td><Status status={character.attribution_status ?? character.detail_status} secondary={character.dialogue_status} /></td>
                <td>
                  <button
                    className="open-detail"
                    type="button"
                    onClick={() => onSelect(character.resource_name)}
                    aria-label={`Open ${character.display_name ?? character.resref}`}
                  >
                    →
                  </button>
                </td>
              </tr>
            ))}
            {!loading && page.items.length === 0 && (
              <tr><td className="empty-state" colSpan={15}>No characters match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination
        page={page}
        loading={loading}
        label="Character table pagination"
        onPageChange={browser.goToPage}
        onPageSizeChange={(size) => browser.update("page_size", size)}
      />
    </section>
  );
}

function DialogueBrowser({ active }: { active: boolean }) {
  const browser = useBrowser(
    "dialogues",
    active,
    DEFAULT_DIALOGUE_QUERY,
    getDialogues,
  );
  const { query, page, loading } = browser;

  return (
    <section className="browser-card tab-panel">
      <BrowserHeading eyebrow="COMPLETE RESOURCE INVENTORY" title="Dialogues" description="Every effective DLG, including resources no CRE currently references." loading={loading} count={page.total} noun="dialogues" />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search DLG resrefs and source paths…"
          label="Full-text search dialogues"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.sort === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <div className="filters">
        <SelectFilter label="Attribution" value={query.attributed} values={BOOLEAN_FILTERS} labels={{ true: "Attributed", false: "Unattributed" }} onChange={(value) => browser.update("attributed", value)} />
        <SelectFilter label="Status" value={query.status} values={DETAIL_STATUSES} onChange={(value) => browser.update("status", value)} />
        <SelectFilter label="Source" value={query.source_kind} values={SOURCE_KINDS} onChange={(value) => browser.update("source_kind", value)} />
        {countFilters(query.q, query.attributed, query.status, query.source_kind) > 0 && (
          <button className="clear-filters" type="button" onClick={browser.reset}>
            Clear filters
          </button>
        )}
      </div>
      <div className={`table-wrap dialogue-table ${loading ? "is-loading" : ""}`}>
        <table>
          <thead>
            <tr>
              <SortHeader label="Dialogue" sort="resource_name" query={page} onSort={browser.sortBy} />
              <SortHeader label="Source" sort="source_kind" query={page} onSort={browser.sortBy} />
              <SortHeader label="Object size" sort="serialized_size" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Lines" sort="dialogue_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="NPC" sort="npc_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Player" sort="player_line_count" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="CREs" sort="character_count" query={page} onSort={browser.sortBy} numeric />
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((dialogue) => (
              <tr key={dialogue.resource_name}>
                <td>
                  <strong className="dialogue-name mono">{dialogue.resource_name}</strong>
                  <span className="source-path" title={dialogue.source_path}>
                    {dialogue.source_path}
                  </span>
                </td>
                <td><span className={`source source-${dialogue.source_kind}`}>{dialogue.source_kind}</span></td>
                <td className="numeric mono">{formatBytes(dialogue.serialized_size)}</td>
                <td className="numeric emphatic">{formatCount(dialogue.dialogue_line_count)}</td>
                <td className="numeric">{formatCount(dialogue.npc_line_count)}</td>
                <td className="numeric">{formatCount(dialogue.player_line_count)}</td>
                <td className="numeric">{formatCount(dialogue.character_count)}</td>
                <td><Status status={dialogue.detail_status} secondary={null} /></td>
              </tr>
            ))}
            {!loading && page.items.length === 0 && (
              <tr><td className="empty-state" colSpan={8}>No dialogues match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        loading={loading}
        label="Dialogue table pagination"
        onPageChange={browser.goToPage}
        onPageSizeChange={(size) => browser.update("page_size", size)}
      />
    </section>
  );
}

function LineBrowser({ active }: { active: boolean }) {
  const browser = useBrowser("lines", active, DEFAULT_LINE_QUERY, getLines);
  const { query, page, loading } = browser;
  const [expandedLineId, setExpandedLineId] = useState<string | null>(null);

  return (
    <section className="browser-card tab-panel">
      <BrowserHeading eyebrow="ADDRESSABLE VOICE WORKLOAD" title="Dialogue lines" description="Validated NPC, player, and journal text with stable DLG state and transition coordinates." loading={loading} count={page.total} noun="records" />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search resolved line text or DLG resrefs…"
          label="Full-text search dialogue lines"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.sort === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <div className="filters">
        <SelectFilter label="Kind" value={query.line_kind} values={["npc", "player", "journal"]} labels={{ npc: "NPC response", player: "Player response", journal: "Journal" }} onChange={(value) => browser.update("line_kind", value)} />
        <SelectFilter label="Attribution" value={query.attributed} values={BOOLEAN_FILTERS} labels={{ true: "Attributed", false: "Unattributed" }} onChange={(value) => browser.update("attributed", value)} />
        <SelectFilter label="Source" value={query.source_kind} values={SOURCE_KINDS} onChange={(value) => browser.update("source_kind", value)} />
        {countFilters(query.q, query.line_kind, query.attributed, query.source_kind) > 0 && (
          <button className="clear-filters" type="button" onClick={browser.reset}>
            Clear filters
          </button>
        )}
      </div>
      <div className={`table-wrap line-table ${loading ? "is-loading" : ""}`}>
        <table>
          <thead>
            <tr>
              <th>Resolved text</th>
              <SortHeader label="Dialogue" sort="dialogue_resource_name" query={page} onSort={browser.sortBy} />
              <SortHeader label="Kind" sort="line_kind" query={page} onSort={browser.sortBy} />
              <SortHeader label="Strref" sort="strref" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="State" sort="state_index" query={page} onSort={browser.sortBy} numeric />
              <SortHeader label="Transition" sort="transition_index" query={page} onSort={browser.sortBy} numeric />
              <th>Context</th>
              <SortHeader label="Object size" sort="serialized_size" query={page} onSort={browser.sortBy} numeric />
              <th className="numeric">CREs</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((line) => (
              <tr key={line.id}>
                <td className="line-text">
                  {line.text == null ? (
                    <span className="muted">Unresolved strref</span>
                  ) : (
                    <button
                      type="button"
                      className={`line-text-toggle ${expandedLineId === line.id ? "is-expanded" : ""}`}
                      aria-expanded={expandedLineId === line.id}
                      title={expandedLineId === line.id ? "Collapse line text" : "Expand full line text"}
                      onClick={() => setExpandedLineId((current) => current === line.id ? null : line.id)}
                    >
                      {line.text}
                    </button>
                  )}
                </td>
                <td>
                  <strong className="dialogue-name mono">{line.dialogue_resource_name}</strong>
                  <span className="source-path">{line.source_kind}</span>
                </td>
                <td><span className={`line-kind line-kind-${line.line_kind}`}>{line.line_kind}</span></td>
                <td className="numeric mono">{line.strref}</td>
                <td className="numeric">{line.state_index}</td>
                <td className="numeric">{formatCount(line.transition_index)}</td>
                <td><LineContext tokens={line.tokens} triggerIndex={line.state_trigger_index} triggerText={line.state_trigger_text} /></td>
                <td className="numeric mono">{formatBytes(line.serialized_size)}</td>
                <td className="numeric">{line.character_count}</td>
              </tr>
            ))}
            {!loading && page.items.length === 0 && (
              <tr><td className="empty-state" colSpan={9}>No dialogue lines match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        loading={loading}
        label="Dialogue line pagination"
        onPageChange={browser.goToPage}
        onPageSizeChange={(size) => browser.update("page_size", size)}
      />
    </section>
  );
}

function Tab({ active, count, label, onClick }: {
  active: boolean; count?: number; label: string; onClick: () => void;
}) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}>
      {label} <span>{formatCount(count)}</span>
    </button>
  );
}

export function LineContext({ tokens, triggerIndex, triggerText }: {
  tokens: string[];
  triggerIndex: number | null;
  triggerText: string | null;
}) {
  if (tokens.length === 0 && triggerIndex == null && triggerText == null) {
    return <span className="muted">—</span>;
  }
  return (
    <div className="line-context">
      {tokens.length > 0 && (
        <div className="definition-tags">
          {tokens.map((token, index) => <span key={`${index}:${token}`}>{token}</span>)}
        </div>
      )}
      {triggerText != null && (
        <details className="table-text-details script-text">
          <summary>State trigger{triggerIndex == null ? "" : ` ${triggerIndex}`}</summary>
          <code>{triggerText}</code>
        </details>
      )}
      {triggerText == null && triggerIndex != null && (
        <span className="muted">State trigger {triggerIndex} · unresolved</span>
      )}
    </div>
  );
}

function Stat({ label, value, note, accent = false }: {
  label: string; value?: number; note: string; accent?: boolean;
}) {
  return (
    <article className={`stat ${accent ? "stat-accent" : ""}`}>
      <span>{label}</span>
      <strong>{formatCount(value)}</strong>
      <p>{note}</p>
    </article>
  );
}

function SupportStat({ label, value }: { label: string; value?: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{formatCount(value)}</strong>
    </div>
  );
}

function Status({ status, secondary }: { status: string; secondary: string | null }) {
  const combined = status === "complete" && secondary != null ? secondary : status;
  return <span className={`status-pill status-${combined}`}>{combined}</span>;
}

function DetailDrawer({ resourceName, detail, error, onClose, onRetry }: {
  resourceName: string;
  detail: CharacterDetailResponse | null;
  error: string | null;
  onClose: () => void;
  onRetry: () => void;
}) {
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const drawer = drawerRef.current;
    if (drawer == null) return undefined;

    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    (drawer.querySelector<HTMLElement>(FOCUSABLE) ?? drawer).focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = focusable.at(0);
      const last = focusable.at(-1);
      const active = document.activeElement;
      if (first == null || last == null) {
        event.preventDefault();
        drawer.focus();
      } else if (!drawer.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [onClose]);

  return (
    <div
      className="drawer-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose();
      }}
    >
      <aside
        ref={drawerRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="character-detail-title"
        tabIndex={-1}
      >
        <div className="drawer-head">
          <div>
            <p className="eyebrow">CHARACTER OBJECT</p>
            <h2 id="character-detail-title">{detail?.character.display_name ?? resourceName}</h2>
            <span className="mono">{resourceName}</span>
          </div>
          <button type="button" onClick={onClose} aria-label="Close details">×</button>
        </div>
        {error != null ? (
          <div className="drawer-loading drawer-error" role="alert">
            <strong>Couldn’t load this character.</strong>
            <p>{error}</p>
            <button type="button" onClick={onRetry}>Retry</button>
          </div>
        ) : detail == null ? (
          <div className="drawer-loading">Loading validated object…</div>
        ) : (
          <div className="drawer-body">
            <section>
              <h3>Overview</h3>
              <dl>
                <Data label="Direct CRE DLG" value={detail.character.dialog_resref ?? "—"} />
                <Data label="Source" value={detail.source_kind} />
                <Data label="CRE version" value={detail.character.cre_version} />
                <Data label="Object JSON" value={formatBytes(detail.character_serialized_size)} />
                <Data label="Updated" value={formatDate(detail.updated_at)} />
              </dl>
            </section>
            {detail.dialogue != null && (
              <section>
                <h3>Direct CRE dialogue workload</h3>
                <div className="metric-grid">
                  <Metric label="Total lines" value={detail.dialogue.dialogue_line_count} />
                  <Metric label="NPC lines" value={detail.dialogue.npc_line_count} />
                  <Metric label="Player lines" value={detail.dialogue.player_line_count} />
                  <Metric label="States" value={detail.dialogue.state_count} />
                  <Metric label="Transitions" value={detail.dialogue.transition_count} />
                </div>
              </section>
            )}
            <section>
              <h3>Classification</h3>
              <dl>
                <Data label="Gender" value={formatDefinition(detail.character.gender_label, detail.character.gender_id)} />
                <Data label="Race" value={formatDefinition(detail.character.race_label, detail.character.race_id)} />
                <Data label="Class" value={formatDefinition(detail.character.class_label, detail.character.class_id)} />
                <Data label="Alignment" value={formatDefinition(detail.character.alignment_label, detail.character.alignment_id)} />
                <Data label="Enemy / ally" value={formatDefinition(detail.character.enemy_ally_label, detail.character.enemy_ally_id)} />
                <Data label="General" value={formatDefinition(detail.character.general_label, detail.character.general_id)} />
                <Data label="Specific" value={formatDefinition(detail.character.specific_label, detail.character.specific_id)} />
                <Data label="Animation" value={formatDefinition(detail.character.animation_label, detail.character.animation_id)} />
                <Data label="Racial enemy" value={formatDefinition(detail.character.racial_enemy_label, detail.character.racial_enemy_id)} />
                <Data label="Kit" value={formatOptionalDefinition(detail.character.kit_label, detail.character.kit_ids_value)} />
                <Data label="Raw CRE kit" value={formatHex(detail.character.cre_kit_value)} />
                <Data label="Class levels" value={formatClassLevels(detail.character)} />
              </dl>
            </section>
            <section>
              <h3>Voice/personality signals</h3>
              <div className="metric-grid">
                <Metric label="Strength" value={detail.character.strength} />
                <Metric label="Strength bonus" value={detail.character.strength_bonus} />
                <Metric label="Intelligence" value={detail.character.intelligence} />
                <Metric label="Wisdom" value={detail.character.wisdom} />
                <Metric label="Dexterity" value={detail.character.dexterity} />
                <Metric label="Constitution" value={detail.character.constitution} />
                <Metric label="Charisma" value={detail.character.charisma} />
                <Metric label="Morale" value={detail.character.morale} />
                <Metric label="Morale break" value={detail.character.morale_break} />
                <Metric label="Morale recovery" value={detail.character.morale_recovery_time} />
                <Metric label="Reputation" value={detail.character.reputation} />
              </div>
            </section>
            <section>
              <h3>Source path</h3>
              <code className="path-code">{detail.source_path}</code>
            </section>
            <details>
              <summary>Full Pydantic JSON</summary>
              <pre>{JSON.stringify(detail, null, 2)}</pre>
            </details>
          </div>
        )}
      </aside>
    </div>
  );
}

function Data({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function ResolvedValue({ label, id, secondary = false }: {
  label: string | null;
  id: number | null;
  secondary?: boolean;
}) {
  return (
    <span className={`resolved-value ${secondary ? "resolved-value-secondary" : ""}`}>
      <strong>{label ?? "Unresolved"}</strong>
      <span className="mono">ID {formatCount(id)}</span>
    </span>
  );
}

function DialogueCoverage({ resolved, declared }: {
  resolved: number | null;
  declared: number | null;
}) {
  return (
    <span className="dialogue-coverage" title="Resolved / declared dialogue resources">
      <strong>{formatCount(resolved)}</strong>
      <span>/ {formatCount(declared)}</span>
    </span>
  );
}

function formatDefinition(label: string, id: number): string {
  return `${label} [${id}]`;
}

function formatOptionalDefinition(label: string | null, id: number | null): string {
  return label == null || id == null ? "—" : formatDefinition(label, id);
}

function formatClassLevels(character: CharacterDetailResponse["character"]): string {
  return [
    character.first_class_level,
    character.second_class_level,
    character.third_class_level,
  ].join(" / ");
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}
