import { listExtractionRuns } from "./api";
import { TableBrowser } from "./browser";
import type { Column } from "./browser";
import { formatBytes, formatCount } from "./format";
import type { ExtractionRun, Installation } from "./gen/bgvoice/v1/pipeline_pb";
import {
  formatTimestamp,
  runKindLabel,
  runStatusLabel,
  toNumber,
} from "./pipeline-labels";
import { Stat, StatusPill, SupportStat } from "./resource-ui";

type RunOrder = "started_at" | "completed_at" | "run_kind" | "status";

const RUN_COLUMNS = [
  {
    label: "Stage",
    orderBy: "run_kind",
    render: (run) => (
      <div className="definition-name">
        <strong>{runKindLabel(run.runKind)}</strong>
        <span className="mono">{run.runId}</span>
      </div>
    ),
  },
  { label: "Started", orderBy: "started_at", render: (run) => formatTimestamp(run.startedAt) },
  { label: "Completed", orderBy: "completed_at", render: (run) => formatTimestamp(run.completedAt) },
  {
    label: "Extracted",
    numeric: true,
    render: (run) => `${formatCount(toNumber(run.detailsExtracted))} / ${formatCount(toNumber(run.resourcesDiscovered))}`,
  },
  { label: "Failures", numeric: true, render: (run) => formatCount(toNumber(run.failures)) },
  {
    label: "Status",
    orderBy: "status",
    render: (run) => <StatusPill value={runStatusLabel(run.status)} />,
  },
] satisfies readonly Column<ExtractionRun, RunOrder>[];

export function PipelinePage({ installation }: { installation: Installation | null }) {
  const {
    voices,
    characters,
    dialogues,
    npcLines,
    playerLines,
    journalLines,
    matchedCharacters,
    unattributedDialogueLines,
    characterSounds,
    dialogueTransitions,
    races,
    characterClasses,
    kits,
    identifierDefinitions,
    generatedVoices,
    uniqueInworldVoices,
    directedLines,
    generatedAudios,
    runningTtsBatches,
    failedTtsBatches,
    voiceCreationFailures,
    dialogueDirectionFailures,
    audioGenerationFailures,
  } = installation?.summary ?? {};
  return (
    <section className="pipeline-page">
      <div className="section-head pipeline-head">
        <div>
          <p className="eyebrow">SYSTEM</p>
          <h1>Pipeline</h1>
          <p>Extraction coverage and recent read-only pipeline activity.</p>
        </div>
        <div className="database-meta">
          <span>Database</span>
          <strong>{formatBytes(toNumber(installation?.databaseSize))}</strong>
        </div>
      </div>
      <div className="stats-grid" aria-label="Pipeline summary">
        <Stat label="Voices" value={voices} />
        <Stat label="Characters" value={characters} />
        <Stat label="Dialogues" value={dialogues} />
        <Stat label="NPC lines" value={npcLines} />
        <Stat label="Player lines" value={playerLines} />
        <Stat label="Journal lines" value={journalLines} />
        <Stat label="Matched characters" value={matchedCharacters} />
        <Stat label="Unattributed lines" value={unattributedDialogueLines} />
      </div>
      <section className="generation-summary" aria-labelledby="generation-summary-title">
        <div>
          <p className="eyebrow">GENERATION</p>
          <h2 id="generation-summary-title">Voice-over progress</h2>
        </div>
        <div className="generation-stats">
          <Stat label="Voice assignments" value={generatedVoices} accent />
          <Stat label="Unique Inworld voices" value={uniqueInworldVoices} />
          <Stat label="Directed lines" value={directedLines} />
          <Stat label="Audio samples" value={generatedAudios} />
        </div>
        <div className="generation-batches">
          <SupportStat label="TTS batches running" value={runningTtsBatches} />
          <SupportStat label="TTS batches failed" value={failedTtsBatches} />
        </div>
        <div className="generation-failures" role="group" aria-label="Generation failures">
          <SupportStat label="Voice creation" value={voiceCreationFailures} />
          <SupportStat label="Dialogue direction" value={dialogueDirectionFailures} />
          <SupportStat label="Audio generation" value={audioGenerationFailures} />
        </div>
      </section>
      <div className="support-stats">
        <SupportStat label="Sounds" value={characterSounds} />
        <SupportStat label="Transitions" value={dialogueTransitions} />
        <SupportStat label="Races" value={races} />
        <SupportStat label="Classes" value={characterClasses} />
        <SupportStat label="Kits" value={kits} />
        <SupportStat label="Identifiers" value={identifierDefinitions} />
      </div>
      <TableBrowser
        defaultOrderBy="started_at desc"
        loadPage={listExtractionRuns}
        columns={RUN_COLUMNS}
        rowKey={(run) => run.name}
        eyebrow="RECENT ACTIVITY"
        title="Extraction runs"
        description="Each pipeline stage attempt, newest first."
        noun="runs"
        searchPlaceholder="Search run IDs and stages…"
        className="runs-browser"
      />
    </section>
  );
}
