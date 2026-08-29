import { listDialogueLines } from "./api";
import {
  BrowserScaffold,
  SelectFilter,
  TextFilter,
} from "./browser";
import type { FilterControls } from "./browser";
import { setExactFilter } from "./filters";
import { formatCount } from "./format";
import type { DialogueLine, DirectedLine } from "./gen/bgvoice/v1/pipeline_pb";
import { SourceBadge } from "./resource-ui";
import { dialoguePath, followLink, voicePath } from "./routes";
import type { DialogueLineKind } from "./routes";
import { useBrowser } from "./use-browser";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const BOOLEAN_FILTERS = ["true", "false"] as const;

const LINE_PAGES = {
  npc: {
    eyebrow: "VOICE PRODUCTION",
    title: "NPC lines",
    description: "Review source dialogue, directed delivery, and generated audio.",
    noun: "NPC lines",
    placeholder: "Search NPC dialogue and resources…",
  },
  player: {
    eyebrow: "DIALOGUE CORPUS",
    title: "Player lines",
    description: "Browse player responses with their exact state-machine location and context.",
    noun: "player lines",
    placeholder: "Search player responses and resources…",
  },
  journal: {
    eyebrow: "QUEST JOURNAL",
    title: "Journal entries",
    description: "Browse quest-journal text with its originating dialogue and transition.",
    noun: "journal entries",
    placeholder: "Search journal text and resources…",
  },
} satisfies Record<DialogueLineKind, {
  eyebrow: string;
  title: string;
  description: string;
  noun: string;
  placeholder: string;
}>;

const LINE_LOADERS = {
  npc: lineLoader("npc"),
  player: lineLoader("player"),
  journal: lineLoader("journal"),
} satisfies Record<DialogueLineKind, typeof listDialogueLines>;

export function DialogueLineBrowser({ lineKind }: { lineKind: DialogueLineKind }) {
  const browser = useBrowser("dialogue asc", LINE_LOADERS[lineKind]);
  const page = LINE_PAGES[lineKind];
  const { result, loading } = browser;
  return (
    <BrowserScaffold
      browser={browser}
      eyebrow={page.eyebrow}
      title={page.title}
      description={page.description}
      noun={page.noun}
      searchPlaceholder={page.placeholder}
      renderFilters={(controls) => <LineFilters lineKind={lineKind} controls={controls} />}
    >
      <div className={`dialogue-line-results ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        {result.items.map((line) => (
          <DialogueLineItem key={line.name} line={line} production={lineKind === "npc"} />
        ))}
        {!loading && result.items.length === 0 && (
          <div className="empty-state">No {page.noun} match this filter.</div>
        )}
      </div>
    </BrowserScaffold>
  );
}

function lineLoader(lineKind: DialogueLineKind): typeof listDialogueLines {
  return (query, signal) => listDialogueLines({
    ...query,
    filter: setExactFilter(query.filter ?? "", "line_kind", lineKind),
  }, signal);
}

function LineFilters({ lineKind, controls }: {
  lineKind: DialogueLineKind;
  controls: FilterControls;
}) {
  const { value, update } = controls;
  return (
    <>
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
      {lineKind === "npc" && (
        <>
          <TextFilter
            label="Voice ID"
            value={value("voice_id")}
            placeholder="imoen"
            onChange={(next) => update("voice_id", next)}
          />
          <SelectFilter
            label="Direction"
            value={value("directed") as "" | "true" | "false"}
            values={BOOLEAN_FILTERS}
            labels={{ true: "Directed", false: "Not directed" }}
            onChange={(next) => update("directed", next === "" ? "" : next === "true")}
          />
          <SelectFilter
            label="Audio"
            value={value("voiced") as "" | "true" | "false"}
            values={BOOLEAN_FILTERS}
            labels={{ true: "Generated", false: "Not generated" }}
            onChange={(next) => update("voiced", next === "" ? "" : next === "true")}
          />
        </>
      )}
    </>
  );
}

function DialogueLineItem({ line, production }: { line: DialogueLine; production: boolean }) {
  const dialogueHref = dialoguePath(line.dialogue);
  return (
    <article className={`dialogue-line-item ${production ? "production-line" : "corpus-line"}`}>
      <header className="dialogue-line-meta">
        <a href={dialogueHref} onClick={(event) => followLink(event, dialogueHref)}>
          {line.dialogueResref}.DLG
        </a>
        <SourceBadge kind={line.sourceKind} />
        <span>State {formatCount(line.stateIndex)}</span>
        {line.transitionIndex != null && <span>Transition {formatCount(line.transitionIndex)}</span>}
        <span>Strref {formatCount(line.strref)}</span>
        <span>
          {formatCount(line.characterCount)} {line.characterCount === 1 ? "character" : "characters"}
        </span>
      </header>
      <div className="dialogue-line-body">
        <section className="dialogue-source-text">
          <h2>Source text</h2>
          <ExpandableLineText value={line.text} />
          <LineContext
            tokens={line.tokens}
            triggerIndex={line.stateTriggerIndex}
            triggerText={line.stateTriggerText}
          />
        </section>
        {production && <LineDirections directions={line.directions} />}
      </div>
    </article>
  );
}

function ExpandableLineText({ value }: { value: string | undefined }) {
  if (value == null) return <p className="muted">Unresolved strref</p>;
  if (value.length <= 240) return <p>{value}</p>;
  return (
    <details className="expandable-copy">
      <summary aria-label="Show full dialogue text">{value}</summary>
      <p>{value}</p>
    </details>
  );
}

function LineDirections({ directions }: { directions: readonly DirectedLine[] }) {
  return (
    <section className="generated-delivery">
      <h2>Generated delivery</h2>
      {directions.length === 0 ? (
        <div className="delivery-empty">
          <strong>Not directed</strong>
          <span>No generated performance exists for this line.</span>
        </div>
      ) : (
        <div className="line-directions">
          {directions.map((direction) => (
            <DirectionCard key={direction.id} direction={direction} />
          ))}
        </div>
      )}
    </section>
  );
}

function DirectionCard({ direction }: { direction: DirectedLine }) {
  const result = directionResult(direction);
  const href = voicePath(direction.voice);
  return (
    <article className="line-direction">
      <div className="line-direction-head">
        <a href={href} onClick={(event) => followLink(event, href)}>
          {direction.voiceDisplayName}
        </a>
        <span>{result.label}</span>
        <i className={direction.audioUrl == null ? "is-pending" : "is-ready"}>
          {direction.audioUrl == null ? "Audio pending" : "Audio ready"}
        </i>
      </div>
      <p>{result.directedDialogue}</p>
      {direction.audioUrl != null && (
        <audio controls preload="none" src={direction.audioUrl} aria-label={result.audioLabel}>
          <a href={direction.audioUrl}>Download audio</a>
        </audio>
      )}
    </article>
  );
}

function directionResult(direction: DirectedLine): {
  label: string;
  directedDialogue: string;
  audioLabel: string;
} {
  switch (direction.result.case) {
    case "character":
      return {
        label: "Character",
        directedDialogue: direction.result.value.directedDialogue,
        audioLabel: `Audio sample for ${direction.voiceDisplayName}`,
      };
    case "narrator":
      return {
        label: "Narrator",
        directedDialogue: direction.result.value.directedDialogue,
        audioLabel: `Narrator audio sample attributed to ${direction.voiceDisplayName}`,
      };
    case undefined:
      throw new Error(`Directed line ${direction.id} has no result`);
  }
}

function LineContext({ tokens, triggerIndex, triggerText }: {
  tokens: readonly string[];
  triggerIndex: number | undefined;
  triggerText: string | undefined;
}) {
  const context = countTokens(tokens);
  if (context.length === 0 && triggerIndex == null && triggerText == null) return null;
  return (
    <div className="line-context">
      {context.length > 0 && (
        <div className="definition-tags" aria-label="Dialogue tokens">
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
      <details className="line-trigger">
        <summary>State trigger{index == null ? "" : ` ${index}`}</summary>
        <code>{text}</code>
      </details>
    );
  }
  return index == null
    ? null
    : <span className="muted">State trigger {index} · unresolved</span>;
}
