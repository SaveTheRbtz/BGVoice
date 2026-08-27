import { useCallback, useEffect, useRef, useState } from "react";

import {
  getCharacterDetail,
  getCharacters,
  getDialogues,
  getFilterOptions,
  getLines,
  getStats,
} from "./api";
import { formatBytes, formatCount, formatDate } from "./format";
import type {
  AttributionStatus,
  CharacterDetailResponse,
  CharacterQuery,
  DetailStatus,
  DialogueQuery,
  FacetValue,
  FilterOptions,
  LineQuery,
  Page,
  PaginatedQuery,
  PipelineStats,
  SourceKind,
  SortDirection,
} from "./types";

const PAGE_SIZES = [10, 25, 50, 100] as const;
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

function useBrowser<
  Item,
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>(
  defaultQuery: Query,
  loadPage: (query: Query, signal: AbortSignal) => Promise<Page<Item, Sort>>,
) {
  const [query, setQuery] = useState(defaultQuery);
  const [search, setSearch] = useState(defaultQuery.q);
  const [page, setPage] = useState<Page<Item, Sort>>(() => ({
    items: [],
    page: 1,
    page_size: defaultQuery.page_size,
    total: 0,
    page_count: 1,
    sort: "relevance",
    direction: defaultQuery.direction,
  }));
  const [loadedQuery, setLoadedQuery] = useState<Query | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const q = search.trim();
      setQuery((current) =>
        current.q === q ? current : { ...current, q, page: 1 },
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    loadPage(query, controller.signal)
      .then((result) => {
        setPage(result);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedQuery(query);
      });
    return () => controller.abort();
  }, [loadPage, query]);

  function update<Key extends keyof Query>(key: Key, value: Query[Key]) {
    setQuery((current) => ({ ...current, [key]: value, page: 1 }));
  }

  function sortBy(sort: Sort) {
    setQuery((current) => ({
      ...current,
      page: 1,
      sort,
      direction:
        page.sort === sort && page.direction === "desc" ? "asc" : "desc",
    }));
  }

  function reset() {
    setSearch("");
    setQuery((current) => ({
      ...defaultQuery,
      page_size: current.page_size,
    }));
  }

  function goToPage(nextPage: number) {
    setQuery((current) => ({
      ...current,
      page: Math.max(1, Math.min(page.page_count, nextPage)),
    }));
  }

  return {
    query,
    search,
    setSearch,
    page,
    loading: loadedQuery !== query,
    error,
    update,
    sortBy,
    reset,
    goToPage,
  };
}

export default function App() {
  const [activeTab, setActiveTab] = useState<
    "characters" | "dialogues" | "lines"
  >("characters");
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
              Inspect characters, dialogue resources, and addressable lines
              without touching pipeline state.
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

        <nav className="view-tabs" role="tablist" aria-label="Pipeline data views">
          <Tab active={activeTab === "characters"} count={stats?.characters_total} label="Characters" onClick={() => setActiveTab("characters")} />
          <Tab active={activeTab === "dialogues"} count={stats?.dialogues_total} label="Dialogues" onClick={() => setActiveTab("dialogues")} />
          <Tab active={activeTab === "lines"} count={stats?.line_records_total} label="Lines" onClick={() => setActiveTab("lines")} />
        </nav>

        {refreshError != null && (
          <ErrorBanner message={refreshError} onDismiss={() => setRefreshError(null)} />
        )}
        {activeTab === "characters" && (
          <CharacterBrowser options={options} onSelect={openDetail} />
        )}
        {activeTab === "dialogues" && <DialogueBrowser />}
        {activeTab === "lines" && <LineBrowser />}

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
  options,
  onSelect,
}: {
  options: FilterOptions | null;
  onSelect: (resourceName: string) => void;
}) {
  const browser = useBrowser(
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
        <ResultCount loading={loading} count={page.total} noun="results" />
      </div>

      <div className="filters" aria-label="Character filters">
        <SelectFilter label="Status" value={query.status} values={DETAIL_STATUSES} onChange={(value) => browser.update("status", value)} />
        <FacetFilter label="Source" value={query.source_kind} values={options?.source_kinds} onChange={(value) => browser.update("source_kind", value)} />
        <SelectFilter label="Dialogue" value={query.has_dialog} values={BOOLEAN_FILTERS} labels={{ true: "Has dialogue", false: "No dialogue" }} onChange={(value) => browser.update("has_dialog", value)} />
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
                    <span>{character.dialog_resref ?? "No DLG"}</span>
                  </button>
                </td>
                <td className="mono">{character.resource_name}</td>
                <td><span className={`source source-${character.source_kind}`}>{character.source_kind}</span></td>
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
              <tr><td className="empty-state" colSpan={11}>No characters match these filters.</td></tr>
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

function DialogueBrowser() {
  const browser = useBrowser(
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

function LineBrowser() {
  const browser = useBrowser(DEFAULT_LINE_QUERY, getLines);
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
                <td className="numeric mono">{formatBytes(line.serialized_size)}</td>
                <td className="numeric">{line.character_count}</td>
              </tr>
            ))}
            {!loading && page.items.length === 0 && (
              <tr><td className="empty-state" colSpan={8}>No dialogue lines match these filters.</td></tr>
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

function BrowserHeading({ eyebrow, title, description, loading, count, noun }: {
  eyebrow: string; title: string; description: string;
  loading: boolean; count: number; noun: string;
}) {
  return (
    <div className="section-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <ResultCount loading={loading} count={count} noun={noun} />
    </div>
  );
}

function SearchBox({ value, onChange, placeholder, label }: {
  value: string; onChange: (value: string) => void;
  placeholder: string; label: string;
}) {
  return (
    <label className="search-box">
      <span aria-hidden="true">⌕</span>
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
      />
    </label>
  );
}

function ResultCount({ loading, count, noun }: {
  loading: boolean; count: number; noun: string;
}) {
  return (
    <div className="result-count" aria-live="polite">
      {loading ? "Loading…" : `${formatCount(count)} ${noun}`}
    </div>
  );
}

function SortHeader<Sort extends string>({ label, sort, query, onSort, numeric = false }: {
  label: string; sort: Sort;
  query: { sort: Sort | "relevance"; direction: SortDirection };
  onSort: (sort: Sort) => void; numeric?: boolean;
}) {
  const active = query.sort === sort;
  const direction = query.direction === "asc" ? "ascending" : "descending";
  return (
    <th className={numeric ? "numeric" : undefined} aria-sort={active ? direction : "none"}>
      <button type="button" onClick={() => onSort(sort)}>
        {label}<span>{active ? (query.direction === "asc" ? "↑" : "↓") : "↕"}</span>
      </button>
    </th>
  );
}

function SelectFilter<Value extends string>({ label, value, values, labels = {}, onChange }: {
  label: string; value: "" | Value; values: readonly Value[];
  labels?: Partial<Record<Value, string>>;
  onChange: (value: "" | Value) => void;
}) {
  return (
    <label className="filter">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as "" | Value)}
      >
        <option value="">All</option>
        {values.map((item) => (
          <option key={item} value={item}>{labels[item] ?? item}</option>
        ))}
      </select>
    </label>
  );
}

function FacetFilter<Value extends string>({ label, value, values, onChange }: {
  label: string; value: "" | Value; values?: FacetValue[];
  onChange: (value: "" | Value) => void;
}) {
  return (
    <label className="filter">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as "" | Value)}
      >
        <option value="">All</option>
        {values?.map((item) => (
          <option key={item.value} value={item.value}>
            {item.value} · {formatCount(item.count)}
          </option>
        ))}
      </select>
    </label>
  );
}

function Pagination({ page, loading, label, onPageChange, onPageSizeChange }: {
  page: Page<unknown, string>; label: string;
  loading: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const start = page.items.length === 0 ? 0 : (page.page - 1) * page.page_size + 1;
  const end = (page.page - 1) * page.page_size + page.items.length;
  return (
    <div className="pagination" aria-busy={loading}>
      <div>
        <label>
          Rows
          <select
            value={page.page_size}
            disabled={loading}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
          >
            {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <span>{formatCount(start)}–{formatCount(end)} of {formatCount(page.total)}</span>
      </div>
      <nav aria-label={label}>
        <button type="button" onClick={() => onPageChange(1)} disabled={loading || page.page <= 1}>«</button>
        <button type="button" onClick={() => onPageChange(page.page - 1)} disabled={loading || page.page <= 1}>‹</button>
        <span>Page <strong>{page.page}</strong> of {page.page_count}</span>
        <button type="button" onClick={() => onPageChange(page.page + 1)} disabled={loading || page.page >= page.page_count}>›</button>
        <button type="button" onClick={() => onPageChange(page.page_count)} disabled={loading || page.page >= page.page_count}>»</button>
      </nav>
    </div>
  );
}

function ErrorBanner({ message, onDismiss }: {
  message: string; onDismiss?: () => void;
}) {
  return (
    <div className="error-banner" role="alert">
      {onDismiss != null && <strong>Couldn’t refresh the database view.</strong>}
      {onDismiss != null && " "}{message}
      {onDismiss != null && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">×</button>
      )}
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
                <Data label="Dialogue" value={detail.character.dialog_resref ?? "—"} />
                <Data label="Source" value={detail.source_kind} />
                <Data label="CRE version" value={detail.character.cre_version} />
                <Data label="Object JSON" value={formatBytes(detail.character_serialized_size)} />
                <Data label="Updated" value={formatDate(detail.updated_at)} />
              </dl>
            </section>
            {detail.dialogue != null && (
              <section>
                <h3>Dialogue workload</h3>
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
                <Data label="Gender ID" value={detail.character.gender_id} />
                <Data label="Race ID" value={detail.character.race_id} />
                <Data label="Class ID" value={detail.character.class_id} />
                <Data label="Alignment ID" value={detail.character.alignment_id} />
              </dl>
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

function Metric({ label, value }: { label: string; value: number }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}

function countFilters(...values: string[]): number {
  return values.filter(Boolean).length;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Unknown error";
}
