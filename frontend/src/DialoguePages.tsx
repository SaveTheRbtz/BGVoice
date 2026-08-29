import { getDialogue, listDialogues } from "./api";
import { ErrorBanner, SelectFilter, TableBrowser } from "./browser";
import type { Column, FilterControls } from "./browser";
import { formatBytes, formatCount } from "./format";
import type { Dialogue } from "./gen/bgvoice/v1/pipeline_pb";
import {
  detailStatusLabel,
  formatTimestamp,
  sourceKindLabel,
  toNumber,
} from "./pipeline-labels";
import { Data, Metric, ResourceTitle, SourceBadge, StatusPill } from "./resource-ui";
import {
  dialogueLinesPath,
  dialoguePath,
  dialogueTransitionsPath,
  followLink,
  resourceId,
} from "./routes";
import { useResource } from "./use-resource";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const DETAIL_FILTERS = ["pending", "complete", "failed"] as const;
const BOOLEAN_FILTERS = ["true", "false"] as const;

type DialogueOrder =
  | "engine_resource_name"
  | "source_kind"
  | "npc_line_count"
  | "character_count";

const DIALOGUE_COLUMNS = [
  {
    label: "Dialogue",
    orderBy: "engine_resource_name",
    render: (dialogue) => (
      <ResourceTitle
        href={dialoguePath(dialogue.name, window.location.search)}
        title={dialogue.engineResourceName}
        subtitle={resourceId(dialogue.name)}
      />
    ),
  },
  { label: "Content", orderBy: "npc_line_count", render: (dialogue) => <DialogueContent dialogue={dialogue} /> },
  { label: "Graph", render: (dialogue) => <DialogueGraph dialogue={dialogue} /> },
  {
    label: "Characters",
    orderBy: "character_count",
    numeric: true,
    render: (dialogue) => formatCount(dialogue.characterCount),
  },
  { label: "Generated work", render: (dialogue) => <GeneratedWork dialogue={dialogue} /> },
  {
    label: "Provenance",
    orderBy: "source_kind",
    render: (dialogue) => (
      <div className="dialogue-provenance">
        <SourceBadge kind={dialogue.source?.kind} />
        <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />
      </div>
    ),
  },
] satisfies readonly Column<Dialogue, DialogueOrder>[];

export function DialogueBrowser() {
  return (
    <TableBrowser
      defaultOrderBy="npc_line_count desc"
      loadPage={listDialogues}
      columns={DIALOGUE_COLUMNS}
      rowKey={(dialogue) => dialogue.name}
      eyebrow="DIALOGUE CORPUS"
      title="Dialogues"
      description="Browse effective DLG resources by content, state-machine size, and generated work."
      noun="dialogues"
      searchPlaceholder="Search dialogue resources and source paths…"
      renderFilters={DialogueFilters}
      tableClassName="dialogue-table"
    />
  );
}

function DialogueContent({ dialogue }: { dialogue: Dialogue }) {
  const href = dialogueLinesPath({
    dialogue_resource_name: dialogue.engineResourceName,
    line_kind: "npc",
  });
  return (
    <span className="dialogue-list-summary">
      <a href={href} onClick={(event) => followLink(event, href)}>
        {formatCount(toNumber(dialogue.detail?.npcLineCount))} NPC lines
      </a>
      <span>
        {formatCount(toNumber(dialogue.detail?.playerLineCount))} player · {formatCount(toNumber(dialogue.detail?.journalLineCount))} journal
      </span>
    </span>
  );
}

function DialogueGraph({ dialogue }: { dialogue: Dialogue }) {
  return (
    <span className="dialogue-list-summary">
      <strong>{formatCount(toNumber(dialogue.detail?.stateCount))} states</strong>
      <span>{formatCount(toNumber(dialogue.detail?.transitionCount))} transitions</span>
    </span>
  );
}

function GeneratedWork({ dialogue }: { dialogue: Dialogue }) {
  return (
    <span className="dialogue-list-summary generated-work-summary">
      <strong>{formatCount(Number(dialogue.generatedAudioCount))} audio lines</strong>
      <span>{formatCount(Number(dialogue.directedLineCount))} directed lines</span>
    </span>
  );
}

function DialogueFilters({ value, update }: FilterControls) {
  return (
    <>
      <SelectFilter
        label="Status"
        value={value("detail_status") as "" | (typeof DETAIL_FILTERS)[number]}
        values={DETAIL_FILTERS}
        onChange={(next) => update("detail_status", next)}
      />
      <SelectFilter
        label="Source"
        value={value("source_kind") as "" | (typeof SOURCE_FILTERS)[number]}
        values={SOURCE_FILTERS}
        onChange={(next) => update("source_kind", next)}
      />
      <SelectFilter
        label="Attribution"
        value={value("attributed") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Attributed", false: "Unattributed" }}
        onChange={(next) => update("attributed", next === "" ? "" : next === "true")}
      />
    </>
  );
}

export function DialogueDetailPage({ name }: { name: string }) {
  const resource = useResource(name, getDialogue);
  const href = dialoguePath(undefined, window.location.search);
  return (
    <article className="detail-page dialogue-detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>
        <span aria-hidden="true">←</span> Back to dialogues
      </a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {resource.value == null && resource.error == null && (
        <p className="detail-loading">Loading dialogue…</p>
      )}
      {resource.value != null && <DialogueDetail dialogue={resource.value} />}
    </article>
  );
}

function DialogueDetail({ dialogue }: { dialogue: Dialogue }) {
  return (
    <>
      <DialogueHeader dialogue={dialogue} />
      <GeneratedWorkPanel dialogue={dialogue} />
      <div className="dialogue-detail-grid">
        <DialogueContentCard dialogue={dialogue} />
        <StateMachineCard dialogue={dialogue} />
        <DialogueResourceDetails dialogue={dialogue} />
      </div>
      <DialogueTechnicalSource dialogue={dialogue} />
    </>
  );
}

function DialogueHeader({ dialogue }: { dialogue: Dialogue }) {
  return (
    <header className="dialogue-resource-head">
      <div>
        <p className="eyebrow">DIALOGUE RESOURCE</p>
        <h1>{dialogue.engineResourceName}</h1>
        <span className="resource-name">{resourceId(dialogue.name)}</span>
      </div>
      <div className="dialogue-resource-status">
        <SourceBadge kind={dialogue.source?.kind} />
        <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />
      </div>
    </header>
  );
}

function GeneratedWorkPanel({ dialogue }: { dialogue: Dialogue }) {
  const lineFilters = { dialogue_resource_name: dialogue.engineResourceName, line_kind: "npc" };
  const allHref = dialogueLinesPath(lineFilters);
  const voicedHref = dialogueLinesPath({ ...lineFilters, voiced: true });
  const audio = Number(dialogue.generatedAudioCount);
  const directed = Number(dialogue.directedLineCount);
  return (
    <section className="dialogue-generated-work" aria-labelledby="dialogue-generated-work-title">
      <div className="dialogue-panel-heading">
        <h2 id="dialogue-generated-work-title">Generated work</h2>
        <p>Unique dialogue lines with direction or generated audio.</p>
      </div>
      <div className="dialogue-generated-metrics" aria-label="Generated work inventory">
        <DialogueMetric label="Audio lines" value={audio} />
        <DialogueMetric label="Directed lines" value={directed} />
      </div>
      <nav className="dialogue-actions" aria-label="Dialogue generated work">
        <a href={allHref} onClick={(event) => followLink(event, allHref)}>Browse NPC lines</a>
        {audio > 0 && (
          <a href={voicedHref} onClick={(event) => followLink(event, voicedHref)}>Play generated audio</a>
        )}
      </nav>
    </section>
  );
}

function DialogueMetric({ label, value }: { label: string; value: number }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}

function DialogueContentCard({ dialogue }: { dialogue: Dialogue }) {
  const filters = { dialogue_resource_name: dialogue.engineResourceName };
  const npcHref = dialogueLinesPath({ ...filters, line_kind: "npc" });
  const playerHref = dialogueLinesPath({ ...filters, line_kind: "player" });
  const journalHref = dialogueLinesPath({ ...filters, line_kind: "journal" });
  return (
    <section className="detail-card dialogue-content-card">
      <h2>Content</h2>
      <div className="dialogue-metric-grid">
        <Metric label="Dialogue lines" value={toNumber(dialogue.detail?.dialogueLineCount)} />
        <Metric label="NPC lines" value={toNumber(dialogue.detail?.npcLineCount)} />
        <Metric label="Player lines" value={toNumber(dialogue.detail?.playerLineCount)} />
        <Metric label="Journal entries" value={toNumber(dialogue.detail?.journalLineCount)} />
      </div>
      <nav className="dialogue-card-links" aria-label="Dialogue content">
        <a href={npcHref} onClick={(event) => followLink(event, npcHref)}>Browse NPC lines <span>→</span></a>
        <a href={playerHref} onClick={(event) => followLink(event, playerHref)}>Browse player lines <span>→</span></a>
        <a href={journalHref} onClick={(event) => followLink(event, journalHref)}>Browse journal entries <span>→</span></a>
      </nav>
    </section>
  );
}

function StateMachineCard({ dialogue }: { dialogue: Dialogue }) {
  const href = dialogueTransitionsPath(dialogue.engineResourceName);
  return (
    <section className="detail-card dialogue-state-card">
      <h2>State machine</h2>
      <div className="dialogue-state-metrics">
        <Metric label="States" value={toNumber(dialogue.detail?.stateCount)} />
        <Metric label="Transitions" value={toNumber(dialogue.detail?.transitionCount)} />
      </div>
      <nav className="dialogue-card-links" aria-label="Dialogue state machine">
        <a href={href} onClick={(event) => followLink(event, href)}>Browse transitions <span>→</span></a>
      </nav>
    </section>
  );
}

function DialogueResourceDetails({ dialogue }: { dialogue: Dialogue }) {
  return (
    <section className="detail-card dialogue-resource-details">
      <h2>Resource details</h2>
      <dl>
        <Data label="Source" value={sourceKindLabel(dialogue.source?.kind)} />
        <Data label="DLG version" value={dialogue.detail?.dlgVersion ?? "—"} />
        <Data label="Characters" value={formatCount(dialogue.characterCount)} />
        <Data label="Object size" value={formatBytes(toNumber(dialogue.serializedSize))} />
        <Data label="Updated" value={formatTimestamp(dialogue.extraction?.updatedAt)} />
        {dialogue.extraction?.error != null && (
          <Data label="Extraction error" value={dialogue.extraction.error} />
        )}
      </dl>
    </section>
  );
}

function DialogueTechnicalSource({ dialogue }: { dialogue: Dialogue }) {
  return (
    <details className="technical-source">
      <summary>Technical source</summary>
      <code>{dialogue.source?.path ?? "—"}</code>
    </details>
  );
}
