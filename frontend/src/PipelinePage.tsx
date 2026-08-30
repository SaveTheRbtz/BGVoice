import { formatBytes, formatCount } from "./format";
import type { Installation } from "./gen/bgvoice/v1/pipeline_pb";
import { toNumber } from "./pipeline-labels";

export function PipelinePage({
  installation,
}: {
  installation: Installation | null;
}) {
  return (
    <section className="pipeline-page">
      <header className="section-head pipeline-head">
        <div>
          <h1>Pipeline</h1>
          <p>Dialogue source data and generated voice-over assets.</p>
        </div>
        <div className="database-meta">
          <span>Database</span>
          <strong>{formatBytes(toNumber(installation?.databaseSize))}</strong>
        </div>
      </header>
      <PipelineOverview installation={installation} />
    </section>
  );
}

function PipelineOverview({ installation }: { installation: Installation | null }) {
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
    readableItems,
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
  const directionFailures = toNumber(dialogueDirectionFailures);
  const lineCounts = [
    { label: "NPC", value: toNumber(npcLines), className: "is-npc" },
    { label: "Player", value: toNumber(playerLines), className: "is-player" },
    { label: "Journal", value: toNumber(journalLines), className: "is-journal" },
  ] as const;
  const totalLines = lineCounts.some((line) => line.value != null)
    ? lineCounts.reduce((total, line) => total + (line.value ?? 0), 0)
    : undefined;
  const hasDirectionFailures = (directionFailures ?? 0) > 0;
  let directionMessage = "Loading generation health";
  if (directionFailures === 0) directionMessage = "No dialogue lines need direction";
  else if (directionFailures != null) {
    directionMessage = `${formatCount(directionFailures)} dialogue ${directionFailures === 1 ? "line needs" : "lines need"} direction`;
  }

  return (
    <div className="pipeline-overview">
      <section className="pipeline-attention" aria-labelledby="pipeline-attention-title">
        <div className={hasDirectionFailures ? "attention-message has-issues" : "attention-message"}>
          <span className="attention-mark" aria-hidden="true">
            {directionFailures == null ? "…" : hasDirectionFailures ? "!" : "✓"}
          </span>
          <h2 id="pipeline-attention-title">{directionMessage}</h2>
        </div>
        <dl className="pipeline-health" aria-label="Generation health">
          <PipelineMetric label="TTS running" value={runningTtsBatches} />
          <PipelineMetric label="TTS failed" value={failedTtsBatches} warning />
          <PipelineMetric label="Voice creation" value={voiceCreationFailures} warning />
          <PipelineMetric label="Audio generation" value={audioGenerationFailures} warning />
        </dl>
      </section>

      <section className="pipeline-panel" aria-labelledby="generated-output-title">
        <h2 id="generated-output-title">Generated output</h2>
        <dl className="pipeline-output-grid">
          <PipelineMetric label="Voice assignments" value={generatedVoices} />
          <PipelineMetric label="Unique Inworld voices" value={uniqueInworldVoices} />
          <PipelineMetric label="Directed lines" value={directedLines} />
          <PipelineMetric label="Audio samples" value={generatedAudios} />
        </dl>
      </section>

      <section className="pipeline-panel corpus-panel" aria-labelledby="dialogue-corpus-title">
        <h2 id="dialogue-corpus-title">Dialogue corpus</h2>
        <dl className="corpus-resources">
          <PipelineMetric label="Voices" value={voices} />
          <PipelineMetric label="Characters" value={characters} />
          <PipelineMetric label="Dialogues" value={dialogues} />
        </dl>
        <div className="line-composition">
          <strong>{formatCount(totalLines)} <span>dialogue lines</span></strong>
          <div
            className="line-composition-bar"
            role="img"
            aria-label={lineCounts.map((line) => `${line.label} ${formatCount(line.value)}`).join(", ")}
          >
            {lineCounts.map((line) => (
              <span
                key={line.label}
                className={line.className}
                style={{ width: `${totalLines == null || totalLines === 0 ? 0 : ((line.value ?? 0) / totalLines) * 100}%` }}
              />
            ))}
          </div>
          <dl className="line-composition-legend">
            {lineCounts.map((line) => (
              <div key={line.label} className={line.className}>
                <dt>{line.label}</dt>
                <dd>{formatCount(line.value)}</dd>
              </div>
            ))}
          </dl>
        </div>
        <dl className="corpus-quality">
          <PipelineMetric label="Matched characters" value={matchedCharacters} />
          <PipelineMetric label="Unattributed lines" value={unattributedDialogueLines} />
        </dl>
      </section>

      <section className="pipeline-panel resource-inventory" aria-labelledby="resource-inventory-title">
        <h2 id="resource-inventory-title">Resource inventory</h2>
        <dl>
          <PipelineMetric label="Character sounds" value={characterSounds} />
          <PipelineMetric label="Dialogue transitions" value={dialogueTransitions} />
          <PipelineMetric label="Races" value={races} />
          <PipelineMetric label="Classes" value={characterClasses} />
          <PipelineMetric label="Kits" value={kits} />
          <PipelineMetric label="Identifiers" value={identifierDefinitions} />
          <PipelineMetric label="Readable items" value={readableItems} />
        </dl>
      </section>
    </div>
  );
}

function PipelineMetric({
  label,
  value,
  warning = false,
}: {
  label: string;
  value: bigint | undefined;
  warning?: boolean;
}) {
  const count = toNumber(value);
  return (
    <div className={warning && (count ?? 0) > 0 ? "is-warning" : undefined}>
      <dt>{label}</dt>
      <dd>{formatCount(count)}</dd>
    </div>
  );
}
