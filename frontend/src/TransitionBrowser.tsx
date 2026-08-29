import { listDialogueTransitions } from "./api";
import { BrowserScaffold, SelectFilter, TextFilter } from "./browser";
import type { FilterControls } from "./browser";
import { formatCount, formatHex } from "./format";
import type { DialogueTransition } from "./gen/bgvoice/v1/pipeline_pb";
import { SourceBadge } from "./resource-ui";
import { dialoguePath, followLink } from "./routes";
import { useBrowser } from "./use-browser";

const BOOLEAN_FILTERS = ["true", "false"] as const;

export function TransitionBrowser() {
  const browser = useBrowser("location asc", listDialogueTransitions);
  const { result, loading } = browser;
  return (
    <BrowserScaffold
      browser={browser}
      eyebrow="DLG STATE MACHINE"
      title="Transitions"
      description="Inspect executable dialogue edges, their conditions, actions, and destinations."
      noun="transitions"
      searchPlaceholder="Search dialogues, triggers, actions, and destinations…"
      renderFilters={TransitionFilters}
      className="transition-browser"
    >
      <div className={`transition-list ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        {result.items.map((transition) => (
          <TransitionEdge key={transition.name} transition={transition} />
        ))}
        {!loading && result.items.length === 0 && (
          <div className="empty-state">No transitions match this filter.</div>
        )}
      </div>
    </BrowserScaffold>
  );
}

function TransitionFilters({ value, update }: FilterControls) {
  return (
    <>
      <TextFilter
        label="DLG resource"
        value={value("dialogue_resource_name")}
        placeholder="IMOEN2J.DLG"
        onChange={(next) => update("dialogue_resource_name", next)}
      />
      <SelectFilter
        label="Destination"
        value={value("terminates_dialog") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Ends dialogue", false: "Continues dialogue" }}
        onChange={(next) => update("terminates_dialog", next === "" ? "" : next === "true")}
      />
    </>
  );
}

function TransitionEdge({ transition }: { transition: DialogueTransition }) {
  const sourceHref = dialoguePath(transition.dialogue);
  return (
    <article className="transition-edge">
      <header className="transition-edge-head">
        <div className="transition-route">
          <a href={sourceHref} onClick={(event) => followLink(event, sourceHref)}>
            {transition.dialogueResref}.DLG · state {formatCount(transition.stateIndex)}
          </a>
          <span aria-hidden="true">→</span>
          <TransitionDestination transition={transition} />
        </div>
        <div className="transition-identity">
          <span>Transition {formatCount(transition.transitionIndex)}</span>
          <SourceBadge kind={transition.sourceKind} />
        </div>
      </header>
      <div className="transition-scripts">
        <ScriptPanel
          label="Trigger"
          index={transition.triggerIndex}
          text={transition.triggerText}
          empty="Unconditional"
        />
        <ScriptPanel
          label="Actions"
          index={transition.actionIndex}
          text={transition.actionText}
          empty="No actions"
        />
      </div>
      <footer className="transition-flags">
        <span className="mono">{formatHex(transition.flagsRaw)}</span>
        {transition.flagsDecoded.map((flag) => (
          <span key={flag}>{flag.replaceAll("_", " ")}</span>
        ))}
      </footer>
    </article>
  );
}

function TransitionDestination({ transition }: { transition: DialogueTransition }) {
  if (transition.terminatesDialogue) return <strong className="transition-end">End dialogue</strong>;
  const resref = transition.nextDialogueResref ?? transition.dialogueResref;
  const label = `${resref}.DLG · ${transition.nextStateIndex == null
    ? "unknown state"
    : `state ${formatCount(transition.nextStateIndex)}`}`;
  if (transition.nextDialogue == null) return <strong>{label}</strong>;
  const href = dialoguePath(transition.nextDialogue);
  return <a href={href} onClick={(event) => followLink(event, href)}>{label}</a>;
}

function ScriptPanel({ label, index, text, empty }: {
  label: string;
  index: number | undefined;
  text: string | undefined;
  empty: string;
}) {
  return (
    <section className="transition-script">
      <header>
        <h2>{label}</h2>
        {index != null && <span>Index {index}</span>}
      </header>
      {text == null ? (
        <p className="muted">{index == null ? empty : "Unresolved"}</p>
      ) : (
        <details>
          <summary>{text}</summary>
          <code>{text}</code>
        </details>
      )}
    </section>
  );
}
