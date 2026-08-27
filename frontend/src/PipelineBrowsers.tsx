import { getSounds, getTransitions, getVoices } from "./api";
import { FacetFilter, SelectFilter, TableBrowser } from "./browser";
import { formatBytes, formatCount, formatHex } from "./format";
import type { Column } from "./browser";
import type {
  FacetValue,
  SoundQuery,
  SoundRow,
  SoundSort,
  TransitionQuery,
  TransitionRow,
  TransitionSort,
  VoiceQuery,
  VoiceRow,
  VoiceSort,
} from "./types";

const BOOLEAN_FILTERS = ["true", "false"] as const;

const DEFAULT_VOICE_QUERY: VoiceQuery = {
  page: 1,
  page_size: 25,
  q: "",
  voice_id: "",
  sort: "",
  direction: "desc",
};

const DEFAULT_SOUND_QUERY: SoundQuery = {
  page: 1,
  page_size: 25,
  q: "",
  slot_id: "",
  sort: "",
  direction: "desc",
};

const DEFAULT_TRANSITION_QUERY: TransitionQuery = {
  page: 1,
  page_size: 25,
  q: "",
  terminates_dialog: "",
  sort: "",
  direction: "asc",
};

const VOICE_COLUMNS = [
  {
    label: "Voice",
    sort: "display_name",
    render: (row) => (
      <div className="definition-name">
        <strong>{row.display_name}</strong>
        <span className="mono">{row.id}</span>
      </div>
    ),
  },
  {
    label: "Starter prompt",
    render: (row) => <StarterPrompt value={row.prompt} />,
  },
  {
    label: "Characters",
    sort: "variant_count",
    render: (row) => (
      <ResourceList count={row.variant_count} values={row.variant_resource_names} noun="characters" />
    ),
  },
  {
    label: "Dialogues",
    sort: "dialogue_count",
    render: (row) => (
      <ResourceList count={row.dialogue_count} values={row.dialogue_resrefs} noun="dialogues" />
    ),
  },
  {
    label: "NPC lines",
    sort: "npc_line_count",
    numeric: true,
    render: (row) => formatCount(row.npc_line_count),
  },
  {
    label: "Object size",
    sort: "serialized_size",
    numeric: true,
    render: (row) => <span className="mono">{formatBytes(row.serialized_size)}</span>,
  },
] satisfies readonly Column<VoiceRow, VoiceSort>[];

const SOUND_COLUMNS = [
  {
    label: "Character",
    sort: "character_resource_name",
    render: (row) => (
      <div className="definition-name">
        <strong>{row.character_name}</strong>
        <span className="mono">{row.character_resource_name}</span>
      </div>
    ),
  },
  {
    label: "Sound slot",
    sort: "slot_id",
    render: (row) => (
      <SoundSlot
        slotId={row.slot_id}
        symbols={row.slot_symbols}
        groups={row.slot_groups}
      />
    ),
  },
  {
    label: "Strref",
    sort: "strref",
    numeric: true,
    render: (row) => <span className="mono">{row.strref}</span>,
  },
  {
    label: "Resolved sound text",
    render: (row) => <ExpandableText value={row.text} unresolved="Unresolved strref" />,
  },
  {
    label: "Object size",
    sort: "serialized_size",
    numeric: true,
    render: (row) => <span className="mono">{formatBytes(row.serialized_size)}</span>,
  },
] satisfies readonly Column<SoundRow, SoundSort>[];

const TRANSITION_COLUMNS = [
  {
    label: "Location",
    sort: "location",
    render: (row) => (
      <div className="definition-name">
        <strong className="mono">{row.dialogue_resource_name}</strong>
        <span>{row.source_kind}</span>
      </div>
    ),
  },
  {
    label: "State",
    sort: "state_index",
    numeric: true,
    render: (row) => row.state_index,
  },
  {
    label: "Transition",
    sort: "transition_index",
    numeric: true,
    render: (row) => row.transition_index,
  },
  {
    label: "Trigger",
    render: (row) => (
      <ScriptText index={row.trigger_index} text={row.trigger_text} empty="Unconditional" />
    ),
  },
  {
    label: "Actions",
    render: (row) => <ScriptText index={row.action_index} text={row.action_text} empty="No actions" />,
  },
  {
    label: "Destination",
    render: (row) => <Destination transition={row} />,
  },
  {
    label: "Flags",
    render: (row) => <TransitionFlags raw={row.flags_raw} decoded={row.flags_decoded} />,
  },
  {
    label: "Object size",
    sort: "serialized_size",
    numeric: true,
    render: (row) => <span className="mono">{formatBytes(row.serialized_size)}</span>,
  },
] satisfies readonly Column<TransitionRow, TransitionSort>[];

export function VoiceBrowser({ active }: { active: boolean }) {
  return (
    <TableBrowser
      tab="voices"
      active={active}
      defaultQuery={DEFAULT_VOICE_QUERY}
      loadPage={getVoices}
      columns={VOICE_COLUMNS}
      rowKey={(row) => row.id}
      eyebrow="CANONICAL VOICE INVENTORY"
      title="Voices"
      description="One reusable voice definition per character name, with its characters and attributed dialogue workload."
      noun="voices"
      searchPlaceholder="Search canonical names, IDs, prompts, characters, and dialogues…"
      renderFilters={({ query }) => <VoiceIdChip voiceId={query.voice_id} />}
      filterValues={(query) => [query.voice_id]}
      className="voice-browser"
      tableClassName="voice-table"
    />
  );
}

export function SoundBrowser({ active, soundSlots }: {
  active: boolean;
  soundSlots: FacetValue[];
}) {
  return (
    <TableBrowser
      tab="sounds"
      active={active}
      defaultQuery={DEFAULT_SOUND_QUERY}
      loadPage={getSounds}
      columns={SOUND_COLUMNS}
      rowKey={(row) => row.key}
      eyebrow="CRE SOUNDSET INVENTORY"
      title="Sounds"
      description="Character sound strings resolved through SNDSLOT.IDS, SPEECH.2DA, and dialog.tlk."
      noun="sounds"
      searchPlaceholder="Search character names, resources, sound slots, and resolved text…"
      renderFilters={({ query, update }) => (
        <FacetFilter
          label="Sound slot"
          value={query.slot_id}
          values={soundSlots}
          onChange={(value) => update("slot_id", value)}
        />
      )}
      filterValues={(query) => [query.slot_id]}
      className="sound-browser"
      tableClassName="sound-table"
    />
  );
}

export function VoiceIdChip({ voiceId }: { voiceId: string }) {
  if (voiceId === "") return null;
  return (
    <span className="active-filter-chip">
      <span>Exact voice</span>
      <strong className="mono">{voiceId}</strong>
    </span>
  );
}

export function TransitionBrowser({ active }: { active: boolean }) {
  return (
    <TableBrowser
      tab="transitions"
      active={active}
      defaultQuery={DEFAULT_TRANSITION_QUERY}
      loadPage={getTransitions}
      columns={TRANSITION_COLUMNS}
      rowKey={(row) => row.id}
      eyebrow="DLG STATE MACHINE"
      title="Transitions"
      description="Executable dialogue edges with conditions, actions, flags, and destinations."
      noun="transitions"
      searchPlaceholder="Search dialogue resrefs, triggers, actions, and destinations…"
      renderFilters={({ query, update }) => (
        <SelectFilter
          label="Destination"
          value={query.terminates_dialog}
          values={BOOLEAN_FILTERS}
          labels={{ true: "Ends dialogue", false: "Continues dialogue" }}
          onChange={(value) => update("terminates_dialog", value)}
        />
      )}
      filterValues={(query) => [query.terminates_dialog]}
      className="transition-browser"
      tableClassName="transition-table"
    />
  );
}

export function StarterPrompt({ value }: { value: string }) {
  return (
    <details className="table-text-details">
      <summary>{value}</summary>
      <p>{value}</p>
    </details>
  );
}

export function ResourceList({ count, values, noun }: {
  count: number;
  values: string[];
  noun: string;
}) {
  if (count === 0) return <span className="muted">None</span>;
  return (
    <details className="resource-list">
      <summary>{formatCount(count)} {noun}</summary>
      <div className="definition-tags">
        {values.map((value) => <span className="mono" key={value}>{value}</span>)}
      </div>
    </details>
  );
}

export function SoundSlot({ slotId, symbols, groups }: {
  slotId: number;
  symbols: string[];
  groups: string[];
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

function ExpandableText({ value, unresolved }: { value: string | null; unresolved: string }) {
  if (value == null) return <span className="muted">{unresolved}</span>;
  return (
    <details className="table-text-details">
      <summary>{value}</summary>
      <p>{value}</p>
    </details>
  );
}

export function ScriptText({ index, text, empty }: {
  index: number | null;
  text: string | null;
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

function Destination({ transition }: { transition: TransitionRow }) {
  if (transition.terminates_dialog) return <span className="status-pill status-no_dialogue">End</span>;
  return (
    <div className="definition-name">
      <strong className="mono">{transition.next_dialog ?? transition.dialogue_resref}</strong>
      <span>State {formatCount(transition.next_state_index)}</span>
    </div>
  );
}

function TransitionFlags({ raw, decoded }: { raw: number; decoded: string[] }) {
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
