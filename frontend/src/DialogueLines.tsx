import { useState } from "react";

import { listDialogueLines } from "./api";
import {
  BrowserHeading,
  CursorPagination,
  ErrorBanner,
  RelevanceButton,
  SearchBox,
  SelectFilter,
  SortHeader,
  TextFilter,
} from "./browser";
import { filterValue } from "./filters";
import { formatCount } from "./format";
import { Speaker, type DialogueLine, type DirectedLine } from "./gen/bgvoice/v1/pipeline_pb";
import { lineKindLabel, sourceKindLabel } from "./pipeline-labels";
import { ResourceTitle } from "./resource-ui";
import { dialoguePath, followLink, resourceId, voicePath } from "./routes";
import { useBrowser } from "./use-browser";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const BOOLEAN_FILTERS = ["true", "false"] as const;

export function DialogueLineBrowser() {
  const browser = useBrowser("", listDialogueLines);
  const { query, result, loading } = browser;
  const [expandedLine, setExpandedLine] = useState<string | null>(null);

  return (
    <section className="browser-card resource-page">
      <BrowserHeading
        eyebrow="VOICE WORKLOAD"
        title="Dialogue lines"
        description="Compare source text with its directed performance and generated audio."
        loading={loading}
        count={Number(result.totalSize)}
        noun="lines"
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search resolved text and dialogue resources…"
          label="Search dialogue lines"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.orderBy === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <LineFilters browser={browser} />
      <div className={`table-wrap line-table ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        <table>
          <LineTableHead orderBy={query.orderBy} onSort={browser.sortBy} />
          <tbody>
            {result.items.map((line) => (
              <DialogueLineRow
                key={line.name}
                line={line}
                expanded={expandedLine === line.name}
                onToggle={() => setExpandedLine((current) => current === line.name ? null : line.name)}
              />
            ))}
            {!loading && result.items.length === 0 && (
              <tr><td className="empty-state" colSpan={8}>No dialogue lines match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <CursorPagination
        pageSize={query.pageSize}
        visibleCount={result.items.length}
        totalSize={Number(result.totalSize)}
        loading={loading}
        hasPrevious={browser.hasPreviousPage}
        hasNext={result.nextPageToken !== ""}
        label="Dialogue line pagination"
        onPrevious={browser.previousPage}
        onNext={browser.nextPage}
        onPageSizeChange={browser.setPageSize}
      />
    </section>
  );
}

function LineFilters({ browser }: {
  browser: ReturnType<typeof useBrowser<DialogueLine>>;
}) {
  const filter = browser.query.filter;
  return (
    <div className="filters">
      <SelectFilter
        label="Kind"
        value={filterValue(filter, "line_kind") as "" | "npc" | "player" | "journal"}
        values={["npc", "player", "journal"]}
        labels={{ npc: "NPC response", player: "Player response", journal: "Journal" }}
        onChange={(next) => browser.updateFilter("line_kind", next)}
      />
      <SelectFilter
        label="Source"
        value={filterValue(filter, "source_kind") as "" | (typeof SOURCE_FILTERS)[number]}
        values={SOURCE_FILTERS}
        onChange={(next) => browser.updateFilter("source_kind", next)}
      />
      <SelectFilter
        label="Attribution"
        value={filterValue(filter, "attributed") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Attributed", false: "Unattributed" }}
        onChange={(next) => browser.updateFilter("attributed", next === "" ? "" : next === "true")}
      />
      <TextFilter
        label="Voice ID"
        value={filterValue(filter, "voice_id")}
        placeholder="imoen"
        onChange={(next) => browser.updateFilter("voice_id", next)}
      />
      <SelectFilter
        label="Direction"
        value={filterValue(filter, "directed") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Directed", false: "Not directed" }}
        onChange={(next) => browser.updateFilter("directed", next === "" ? "" : next === "true")}
      />
      <SelectFilter
        label="Audio"
        value={filterValue(filter, "voiced") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Generated", false: "Not generated" }}
        onChange={(next) => browser.updateFilter("voiced", next === "" ? "" : next === "true")}
      />
      {filter !== "" && (
        <button className="clear-filters" type="button" onClick={browser.reset}>Clear filters</button>
      )}
    </div>
  );
}

function LineTableHead({ orderBy, onSort }: {
  orderBy: string;
  onSort: (field: string) => void;
}) {
  return (
    <thead>
      <tr>
        <th>Resolved text</th>
        <SortHeader label="Dialogue" orderBy="dialogue" activeOrderBy={orderBy} onSort={onSort} />
        <SortHeader label="Kind" orderBy="line_kind" activeOrderBy={orderBy} onSort={onSort} />
        <SortHeader label="Strref" orderBy="strref" activeOrderBy={orderBy} onSort={onSort} numeric />
        <SortHeader label="State" orderBy="state_index" activeOrderBy={orderBy} onSort={onSort} numeric />
        <SortHeader label="Transition" orderBy="transition_index" activeOrderBy={orderBy} onSort={onSort} numeric />
        <th>Context</th>
        <th className="numeric">Characters</th>
      </tr>
    </thead>
  );
}

function DialogueLineRow({ line, expanded, onToggle }: {
  line: DialogueLine;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <tr>
      <td className="line-text">
        {line.text == null ? <span className="muted">Unresolved strref</span> : (
          <button
            type="button"
            className={`line-text-toggle ${expanded ? "is-expanded" : ""}`}
            aria-expanded={expanded}
            onClick={onToggle}
          >
            {line.text}
          </button>
        )}
        <LineDirections directions={line.directions} />
      </td>
      <td>
        <ResourceTitle
          href={dialoguePath(line.dialogue)}
          title={resourceId(line.dialogue)}
          subtitle={sourceKindLabel(line.sourceKind)}
        />
      </td>
      <td><span className="line-kind">{lineKindLabel(line.lineKind)}</span></td>
      <td className="numeric mono">{line.strref}</td>
      <td className="numeric">{line.stateIndex}</td>
      <td className="numeric">{formatCount(line.transitionIndex)}</td>
      <td>
        <LineContext
          tokens={line.tokens}
          triggerIndex={line.stateTriggerIndex}
          triggerText={line.stateTriggerText}
        />
      </td>
      <td className="numeric">{formatCount(line.characterCount)}</td>
    </tr>
  );
}

function LineDirections({ directions }: { directions: readonly DirectedLine[] }) {
  if (directions.length === 0) return null;
  return (
    <div className="line-directions" aria-label="Generated performances">
      {directions.map((direction) => (
        <article className="line-direction" key={direction.id}>
          <div className="line-direction-head">
            <a
              href={voicePath(direction.voice)}
              onClick={(event) => followLink(event, voicePath(direction.voice))}
            >
              {direction.voiceDisplayName}
            </a>
            <span>{speakerLabel(direction.speaker)}</span>
          </div>
          <p>{direction.text}</p>
          {direction.audioUrl == null ? (
            <small>Audio pending</small>
          ) : (
            <audio
              controls
              preload="none"
              src={direction.audioUrl}
              aria-label={`Audio sample for ${direction.voiceDisplayName}`}
            >
              <a href={direction.audioUrl}>Download audio</a>
            </audio>
          )}
        </article>
      ))}
    </div>
  );
}

function speakerLabel(speaker: Speaker): string {
  if (speaker === Speaker.NARRATOR) return "Narrator";
  if (speaker === Speaker.CHARACTER) return "Character";
  return "Speaker";
}

function LineContext({ tokens, triggerIndex, triggerText }: {
  tokens: readonly string[];
  triggerIndex: number | undefined;
  triggerText: string | undefined;
}) {
  if (tokens.length === 0 && triggerIndex == null && triggerText == null) {
    return <span className="muted">—</span>;
  }
  const context = countTokens(tokens);
  return (
    <div className="line-context">
      {context.length > 0 && (
        <div className="definition-tags">
          {context.map(([token, count]) => (
            <span key={token}>{token}{count > 1 && `×${count}`}</span>
          ))}
        </div>
      )}
      <StateTrigger index={triggerIndex} text={triggerText} />
    </div>
  );
}

function countTokens(tokens: readonly string[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
  return [...counts].sort(
    ([left, leftCount], [right, rightCount]) => rightCount - leftCount || left.localeCompare(right),
  );
}

function StateTrigger({ index, text }: {
  index: number | undefined;
  text: string | undefined;
}) {
  if (text != null) {
    return (
      <details className="table-text-details script-text">
        <summary>State trigger{index == null ? "" : ` ${index}`}</summary>
        <code>{text}</code>
      </details>
    );
  }
  return index == null
    ? null
    : <span className="muted">State trigger {index} · unresolved</span>;
}
