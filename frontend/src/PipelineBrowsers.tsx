import { getTransitions, getVoices } from "./api";
import { SelectFilter, TableBrowser } from "./browser";
import { formatBytes, formatCount, formatHex } from "./format";
import type { Column } from "./browser";
import type {
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
  has_dialogue: "",
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
    label: "CRE variants",
    sort: "variant_count",
    render: (row) => (
      <ResourceList count={row.variant_count} values={row.variant_resource_names} noun="variants" />
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
      description="One reusable voice definition per canonical speaker, with every CRE variant and direct dialogue workload."
      noun="voices"
      searchPlaceholder="Search canonical names, IDs, prompts, variants, and dialogues…"
      renderFilters={({ query, update }) => (
        <>
          <SelectFilter
            label="Dialogue"
            value={query.has_dialogue}
            values={BOOLEAN_FILTERS}
            labels={{ true: "Has dialogue", false: "No dialogue" }}
            onChange={(value) => update("has_dialogue", value)}
          />
          <VoiceIdChip voiceId={query.voice_id} />
        </>
      )}
      filterValues={(query) => [query.voice_id, query.has_dialogue]}
      className="voice-browser"
      tableClassName="voice-table"
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
