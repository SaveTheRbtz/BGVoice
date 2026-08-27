import { listCharacterSounds, listDialogueTransitions } from "./api";
import { NumberFilter, SelectFilter, TableBrowser } from "./browser";
import type { Column, FilterControls } from "./browser";
import { formatBytes, formatCount, formatHex } from "./format";
import type {
  CharacterSound,
  DialogueTransition,
} from "./gen/bgvoice/v1/pipeline_pb";
import { sourceKindLabel } from "./pipeline-labels";
import { dialoguePath, followLink, resourceId } from "./routes";

const BOOLEAN_FILTERS = ["true", "false"] as const;

type SoundOrder = "character" | "slot_id" | "strref" | "serialized_size";

type TransitionOrder =
  | "location"
  | "dialogue"
  | "state_index"
  | "transition_index"
  | "serialized_size";

const SOUND_COLUMNS = [
  {
    label: "Character",
    orderBy: "character",
    render: (row) => (
      <div className="definition-name">
        <strong>{row.characterDisplayName}</strong>
        <span className="mono">{resourceId(row.character)}</span>
      </div>
    ),
  },
  {
    label: "Sound slot",
    orderBy: "slot_id",
    render: (row) => (
      <SoundSlot slotId={row.slotId} symbols={row.slotSymbols} groups={row.slotGroups} />
    ),
  },
  {
    label: "Strref",
    orderBy: "strref",
    numeric: true,
    render: (row) => <span className="mono">{row.strref}</span>,
  },
  {
    label: "Resolved sound text",
    render: (row) => <ExpandableText value={row.text} unresolved="Unresolved strref" />,
  },
  {
    label: "Object size",
    orderBy: "serialized_size",
    numeric: true,
    render: (row) => <span className="mono">{formatBytes(Number(row.serializedSize))}</span>,
  },
] satisfies readonly Column<CharacterSound, SoundOrder>[];

export function SoundBrowser() {
  return (
    <TableBrowser
      loadPage={listCharacterSounds}
      columns={SOUND_COLUMNS}
      rowKey={(row) => row.name}
      eyebrow="CRE SOUNDSET INVENTORY"
      title="Character sounds"
      description="Resolved soundset strings that help establish how each character already sounds in game."
      noun="sounds"
      searchPlaceholder="Search characters, slots, and resolved sound text…"
      renderFilters={({ value, update }) => (
        <NumberFilter
          label="Sound slot"
          value={value("slot_id")}
          onChange={(next) => update("slot_id", next)}
        />
      )}
      className="sound-browser"
      tableClassName="sound-table"
    />
  );
}

const TRANSITION_COLUMNS = [
  {
    label: "Location",
    orderBy: "location",
    render: (row) => <TransitionLocation transition={row} />,
  },
  { label: "State", orderBy: "state_index", numeric: true, render: (row) => row.stateIndex },
  {
    label: "Transition",
    orderBy: "transition_index",
    numeric: true,
    render: (row) => row.transitionIndex,
  },
  {
    label: "Trigger",
    render: (row) => <ScriptText index={row.triggerIndex} text={row.triggerText} empty="Unconditional" />,
  },
  {
    label: "Actions",
    render: (row) => <ScriptText index={row.actionIndex} text={row.actionText} empty="No actions" />,
  },
  { label: "Destination", render: (row) => <Destination transition={row} /> },
  {
    label: "Flags",
    render: (row) => <TransitionFlags raw={row.flagsRaw} decoded={row.flagsDecoded} />,
  },
  {
    label: "Object size",
    orderBy: "serialized_size",
    numeric: true,
    render: (row) => <span className="mono">{formatBytes(Number(row.serializedSize))}</span>,
  },
] satisfies readonly Column<DialogueTransition, TransitionOrder>[];

export function TransitionBrowser() {
  return (
    <TableBrowser
      defaultOrderBy="location asc"
      loadPage={listDialogueTransitions}
      columns={TRANSITION_COLUMNS}
      rowKey={(row) => row.name}
      eyebrow="DLG STATE MACHINE"
      title="Dialogue transitions"
      description="Executable dialogue edges with conditions, actions, flags, and destinations."
      noun="transitions"
      searchPlaceholder="Search dialogues, triggers, actions, and destinations…"
      renderFilters={TransitionFilters}
      className="transition-browser"
      tableClassName="transition-table"
    />
  );
}

function TransitionFilters({ value, update }: FilterControls) {
  return (
    <SelectFilter
      label="Destination"
      value={value("terminates_dialog") as "" | "true" | "false"}
      values={BOOLEAN_FILTERS}
      labels={{ true: "Ends dialogue", false: "Continues dialogue" }}
      onChange={(next) => update("terminates_dialog", next === "" ? "" : next === "true")}
    />
  );
}

function TransitionLocation({ transition }: { transition: DialogueTransition }) {
  const href = dialoguePath(transition.dialogue);
  return (
    <a
      className="definition-name resource-title"
      href={href}
      onClick={(event) => followLink(event, href)}
    >
      <strong className="mono">{resourceId(transition.dialogue)}</strong>
      <span>{sourceKindLabel(transition.sourceKind)}</span>
    </a>
  );
}

export function SoundSlot({ slotId, symbols, groups }: {
  slotId: number;
  symbols: readonly string[];
  groups: readonly string[];
}) {
  return (
    <div className="definition-name">
      <strong>{symbols[0]?.replaceAll("_", " ") ?? `Slot ${slotId}`}</strong>
      <span className="mono">
        ID {slotId}{symbols.length > 1 ? ` · ${symbols.slice(1).join(", ")}` : ""}
      </span>
      {groups.length > 0 && (
        <span>SPEECH · {groups.map((group) => group.replaceAll("_", " ")).join(", ")}</span>
      )}
    </div>
  );
}

function ExpandableText({ value, unresolved }: { value: string | undefined; unresolved: string }) {
  if (value == null) return <span className="muted">{unresolved}</span>;
  return (
    <details className="table-text-details">
      <summary>{value}</summary>
      <p>{value}</p>
    </details>
  );
}

export function ScriptText({ index, text, empty }: {
  index: number | undefined;
  text: string | undefined;
  empty: string;
}) {
  if (text == null) {
    return <span className="muted">{index == null ? empty : `Index ${index} · unresolved`}</span>;
  }
  return (
    <details className="table-text-details script-text">
      <summary>{text}</summary>
      <code>{text}</code>
      {index != null && <small>Index {index}</small>}
    </details>
  );
}

function Destination({ transition }: { transition: DialogueTransition }) {
  if (transition.terminatesDialogue) {
    return <span className="status-pill status-no-dialogue">End</span>;
  }
  const resref = transition.nextDialogueResref ?? transition.dialogueResref;
  if (transition.nextDialogue == null) {
    return (
      <div className="definition-name">
        <strong className="mono">{resref}</strong>
        <span>State {formatCount(transition.nextStateIndex)}</span>
      </div>
    );
  }
  const href = dialoguePath(transition.nextDialogue);
  return (
    <a className="definition-name resource-title" href={href} onClick={(event) => followLink(event, href)}>
      <strong className="mono">{resref}</strong>
      <span>State {formatCount(transition.nextStateIndex)}</span>
    </a>
  );
}

function TransitionFlags({ raw, decoded }: { raw: number; decoded: readonly string[] }) {
  return (
    <div className="transition-flags">
      <span className="mono">{formatHex(raw)}</span>
      {decoded.length > 0 && (
        <div className="definition-tags">
          {decoded.map((flag) => <span key={flag}>{flag.replaceAll("_", " ")}</span>)}
        </div>
      )}
    </div>
  );
}
