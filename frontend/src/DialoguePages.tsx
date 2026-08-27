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
import {
  Data,
  Metric,
  ResourceTitle,
  SourceBadge,
  StatusPill,
} from "./resource-ui";
import { dialogueLinesPath, dialoguePath, followLink } from "./routes";
import { useResource } from "./use-resource";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const DETAIL_FILTERS = ["pending", "complete", "failed"] as const;
const BOOLEAN_FILTERS = ["true", "false"] as const;

type DialogueOrder =
  | "engine_resource_name"
  | "source_kind"
  | "serialized_size"
  | "dialogue_line_count"
  | "npc_line_count"
  | "player_line_count"
  | "character_count";

const DIALOGUE_COLUMNS = [
  {
    label: "Dialogue",
    orderBy: "engine_resource_name",
    render: (dialogue) => (
      <ResourceTitle
        href={dialoguePath(dialogue.name)}
        title={dialogue.engineResourceName}
        subtitle={dialogue.source?.path ?? dialogue.name}
      />
    ),
  },
  {
    label: "Source",
    orderBy: "source_kind",
    render: (dialogue) => <SourceBadge kind={dialogue.source?.kind} />,
  },
  {
    label: "Lines",
    orderBy: "dialogue_line_count",
    numeric: true,
    render: (dialogue) => <strong>{formatCount(toNumber(dialogue.detail?.dialogueLineCount))}</strong>,
  },
  {
    label: "NPC",
    orderBy: "npc_line_count",
    numeric: true,
    render: (dialogue) => formatCount(toNumber(dialogue.detail?.npcLineCount)),
  },
  {
    label: "Player",
    orderBy: "player_line_count",
    numeric: true,
    render: (dialogue) => formatCount(toNumber(dialogue.detail?.playerLineCount)),
  },
  {
    label: "Characters",
    orderBy: "character_count",
    numeric: true,
    render: (dialogue) => formatCount(dialogue.characterCount),
  },
  {
    label: "Generation",
    numeric: true,
    render: (dialogue) => (
      <GenerationCoverage
        directed={Number(dialogue.directedLineCount)}
        audio={Number(dialogue.generatedAudioCount)}
        total={toNumber(dialogue.detail?.npcLineCount) ?? 0}
      />
    ),
  },
  {
    label: "Object size",
    orderBy: "serialized_size",
    numeric: true,
    render: (dialogue) => <span className="mono">{formatBytes(toNumber(dialogue.serializedSize))}</span>,
  },
  {
    label: "Status",
    render: (dialogue) => <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />,
  },
] satisfies readonly Column<Dialogue, DialogueOrder>[];

export function DialogueBrowser() {
  return (
    <TableBrowser
      loadPage={listDialogues}
      columns={DIALOGUE_COLUMNS}
      rowKey={(dialogue) => dialogue.name}
      eyebrow="DIALOGUE GRAPH"
      title="Dialogues"
      description="Every effective DLG resource, including dialogues no character currently references."
      noun="dialogues"
      searchPlaceholder="Search dialogue resources and source paths…"
      renderFilters={DialogueFilters}
      tableClassName="dialogue-table"
    />
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
  const href = "/dialogues";
  return (
    <section className="detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>← Dialogues</a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {resource.value == null && resource.error == null && (
        <div className="detail-loading">Loading dialogue…</div>
      )}
      {resource.value != null && <DialogueDetail dialogue={resource.value} />}
    </section>
  );
}

function DialogueDetail({ dialogue }: { dialogue: Dialogue }) {
  return (
    <>
      <header className="resource-detail-head">
        <div>
          <p className="eyebrow">DIALOGUE RESOURCE</p>
          <h1>{dialogue.engineResourceName}</h1>
          <span className="resource-name">{dialogue.name}</span>
        </div>
        <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />
      </header>
      <div className="detail-columns">
        <DialogueOverview dialogue={dialogue} />
        <StateMachine dialogue={dialogue} />
      </div>
      <DialogueGeneration dialogue={dialogue} />
      <section className="detail-card source-card">
        <h2>Source path</h2>
        <code>{dialogue.source?.path ?? "—"}</code>
      </section>
    </>
  );
}

function DialogueGeneration({ dialogue }: { dialogue: Dialogue }) {
  const common = { dialogue_resource_name: dialogue.engineResourceName, line_kind: "npc" };
  const allHref = dialogueLinesPath(common);
  const voicedHref = dialogueLinesPath({ ...common, voiced: true });
  return (
    <section className="detail-card generation-detail-card">
      <div>
        <h2>Voice generation</h2>
        <p>Track directed performances and completed audio for this dialogue.</p>
      </div>
      <GenerationCoverage
        directed={Number(dialogue.directedLineCount)}
        audio={Number(dialogue.generatedAudioCount)}
        total={toNumber(dialogue.detail?.npcLineCount) ?? 0}
      />
      <nav className="generation-links" aria-label="Dialogue voice generation">
        <a href={allHref} onClick={(event) => followLink(event, allHref)}>Browse NPC lines</a>
        <a href={voicedHref} onClick={(event) => followLink(event, voicedHref)}>Play generated audio</a>
      </nav>
    </section>
  );
}

function GenerationCoverage({ directed, audio, total }: {
  directed: number;
  audio: number;
  total: number;
}) {
  return (
    <div className="generation-coverage" aria-label={`${audio} audio, ${directed} directed, ${total} source lines`}>
      <strong>{formatCount(audio)} audio</strong>
      <span>{formatCount(directed)} directed / {formatCount(total)} source</span>
    </div>
  );
}

function DialogueOverview({ dialogue }: { dialogue: Dialogue }) {
  return (
    <section className="detail-card">
      <h2>Overview</h2>
      <dl>
        <Data label="Source" value={sourceKindLabel(dialogue.source?.kind)} />
        <Data label="DLG version" value={dialogue.detail?.dlgVersion ?? "—"} />
        <Data label="Object size" value={formatBytes(toNumber(dialogue.serializedSize))} />
        <Data label="Characters" value={formatCount(dialogue.characterCount)} />
        <Data label="Updated" value={formatTimestamp(dialogue.extraction?.updatedAt)} />
        {dialogue.extraction?.error != null && (
          <Data label="Extraction error" value={dialogue.extraction.error} />
        )}
      </dl>
    </section>
  );
}

function StateMachine({ dialogue }: { dialogue: Dialogue }) {
  const detail = dialogue.detail;
  return (
    <section className="detail-card">
      <h2>State machine</h2>
      <div className="metric-grid">
        <Metric label="Lines" value={toNumber(detail?.dialogueLineCount)} />
        <Metric label="NPC lines" value={toNumber(detail?.npcLineCount)} />
        <Metric label="Player lines" value={toNumber(detail?.playerLineCount)} />
        <Metric label="Journal lines" value={toNumber(detail?.journalLineCount)} />
        <Metric label="States" value={toNumber(detail?.stateCount)} />
        <Metric label="Transitions" value={toNumber(detail?.transitionCount)} />
      </div>
    </section>
  );
}
