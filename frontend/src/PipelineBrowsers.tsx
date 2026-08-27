import { useEffect, useState } from "react";
import { portraitUrl } from "./api";
import type { ListQuery, ListResult } from "./api";

import {
  BrowserHeading,
  CursorPagination,
  ErrorBanner,
  NumberFilter,
  RelevanceButton,
  SearchBox,
  SelectFilter,
  TableBrowser,
} from "./browser";
import type { Column } from "./browser";
import {
  characterPath,
  dialoguePath,
  errorMessage,
  followLink,
  listSearch,
  resourceId,
  useBrowser,
  voicePath,
} from "./browser-state";
import { formatBytes, formatCount, formatHex } from "./format";
import { SourceKind } from "./gen/bgvoice/v1/pipeline_pb";
import type {
  CharacterReference,
  CharacterSound,
  DialogueReference,
  DialogueTransition,
  Voice,
} from "./gen/bgvoice/v1/pipeline_pb";

const BOOLEAN_FILTERS = ["true", "false"] as const;

type SoundOrder =
  | "character"
  | "slot_id"
  | "strref"
  | "serialized_size";

type TransitionOrder =
  | "location"
  | "dialogue"
  | "state_index"
  | "transition_index"
  | "serialized_size";

export interface VoiceBrowserProps {
  voiceId: string | null;
  loadVoices: (
    query: ListQuery,
    signal: AbortSignal,
  ) => Promise<ListResult<Voice>>;
  loadVoice: (voiceId: string, signal: AbortSignal) => Promise<Voice>;
}

type VoiceDetailState =
  | { name: string; voice: Voice; error?: never }
  | { name: string; voice?: never; error: string };

export function VoiceBrowser({ voiceId, loadVoices, loadVoice }: VoiceBrowserProps) {
  const browser = useBrowser<Voice>("npc_line_count desc", loadVoices);
  const { query, result, loading } = browser;
  const listed = voiceId == null
    ? null
    : result.items.find((voice) => voice.name === voiceId) ?? null;
  const search = listSearch(query, "npc_line_count desc");
  const [detail, setDetail] = useState<VoiceDetailState | null>(null);

  useEffect(() => {
    if (voiceId == null || listed != null) return undefined;
    const controller = new AbortController();
    loadVoice(voiceId, controller.signal)
      .then((voice) => setDetail({ name: voiceId, voice }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setDetail({ name: voiceId, error: errorMessage(reason) });
        }
      });
    return () => controller.abort();
  }, [listed, loadVoice, voiceId]);

  const selected = listed ?? (detail?.name === voiceId ? detail.voice ?? null : null);
  const detailError = detail?.name === voiceId ? detail.error ?? null : null;

  return (
    <section className="voice-page">
      <BrowserHeading
        eyebrow="VOICE WORKSPACE"
        title="Voices"
        description="Review each reusable character voice, its visual identity, and the prompt that will guide generation."
        loading={loading}
        count={Number(result.totalSize)}
        noun="voices"
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar voice-toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search names, prompts, characters, and dialogues…"
          label="Search voices"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.orderBy === ""}
          onClick={browser.sortByRelevance}
        />
        <label className="filter voice-order">
          <span>Order</span>
          <select
            value={query.orderBy}
            onChange={(event) => browser.setOrderBy(event.target.value)}
          >
            {browser.search !== "" && <option value="">Relevance</option>}
            <option value="npc_line_count desc">NPC lines</option>
            <option value="display_name asc">Name</option>
            <option value="character_count desc">Characters</option>
            <option value="dialogue_count desc">Dialogues</option>
          </select>
        </label>
      </div>

      <div className="voice-layout">
        <div className={`voice-list ${loading ? "is-loading" : ""}`} aria-busy={loading}>
          {result.items.map((voice) => (
            <VoiceCard
              key={voice.name}
              voice={voice}
              selected={selected?.name === voice.name}
              search={search}
            />
          ))}
          {!loading && result.items.length === 0 && (
            <div className="voice-empty">No voices match this filter.</div>
          )}
          <CursorPagination
            pageSize={query.pageSize}
            visibleCount={result.items.length}
            totalSize={Number(result.totalSize)}
            loading={loading}
            hasPrevious={browser.hasPreviousPage}
            hasNext={result.nextPageToken !== ""}
            label="Voice pagination"
            onPrevious={browser.previousPage}
            onNext={browser.nextPage}
            onPageSizeChange={browser.setPageSize}
          />
        </div>
        <VoiceDetail voice={selected} requestedId={voiceId} error={detailError} search={search} />
      </div>
    </section>
  );
}

export function VoiceCard({ voice, selected, search = "" }: {
  voice: Voice;
  selected: boolean;
  search?: string;
}) {
  const href = voicePath(voice.name, search);
  return (
    <a
      className={`voice-card ${selected ? "is-selected" : ""}`}
      href={href}
      aria-current={selected ? "page" : undefined}
      onClick={(event) => followLink(event, href)}
    >
      <VoiceAvatar voice={voice} size="small" />
      <span className="voice-card-copy">
        <strong>{voice.displayName}</strong>
        <span className="voice-prompt-preview">{voice.prompt}</span>
        <span className="voice-card-metrics">
          {formatCount(Number(voice.npcLineCount))} NPC lines · {formatCount(voice.characterCount)} characters
        </span>
      </span>
    </a>
  );
}

export function VoiceAvatar({ voice, size = "large" }: {
  voice: Pick<Voice, "displayName" | "portrait">;
  size?: "small" | "large";
}) {
  const initials = voice.displayName
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  return (
    <span className={`voice-avatar voice-avatar-${size}`} aria-hidden="true">
      <span>{initials}</span>
      {voice.portrait != null && (
        <img
          src={portraitUrl(voice.portrait)}
          alt=""
          loading="lazy"
          onError={(event) => { event.currentTarget.hidden = true; }}
        />
      )}
    </span>
  );
}

export function VoiceDetail({ voice, requestedId, error, search = "" }: {
  voice: Voice | null;
  requestedId: string | null;
  error: string | null;
  search?: string;
}) {
  if (error != null) {
    return <aside className="voice-detail voice-detail-empty"><ErrorBanner message={error} /></aside>;
  }
  if (voice == null) {
    return (
      <aside className="voice-detail voice-detail-empty">
        <div className="voice-detail-placeholder" aria-hidden="true">♪</div>
        <h2>{requestedId == null ? "Choose a voice" : "Loading voice…"}</h2>
        <p>Select a character voice to inspect its prompt and source resources.</p>
      </aside>
    );
  }
  const listHref = voicePath(undefined, search);
  return (
    <aside className="voice-detail">
      <a className="back-link" href={listHref} onClick={(event) => followLink(event, listHref)}>← All voices</a>
      <header className="voice-profile">
        <VoiceAvatar voice={voice} />
        <div>
          <p className="eyebrow">CANONICAL VOICE</p>
          <h2>{voice.displayName}</h2>
          <span className="resource-name">{voice.name}</span>
        </div>
      </header>
      <div className="voice-metrics" aria-label="Voice workload">
        <VoiceMetric label="NPC lines" value={Number(voice.npcLineCount)} primary />
        <VoiceMetric label="Characters" value={voice.characterCount} />
        <VoiceMetric label="Dialogues" value={voice.dialogueCount} />
      </div>
      <section className="prompt-card">
        <div>
          <p className="eyebrow">VOICE CREATION PROMPT</p>
          <span>
            {voice.biography == null
              ? "Derived from current character metadata"
              : `Includes ${resourceId(voice.biography)}`}
          </span>
        </div>
        <p>{voice.prompt}</p>
      </section>
      <ResourceLinks title="Characters" references={voice.characters} kind="character" />
      <ResourceLinks title="Dialogues" references={voice.dialogues} kind="dialogue" />
    </aside>
  );
}

function VoiceMetric({ label, value, primary = false }: {
  label: string;
  value: number;
  primary?: boolean;
}) {
  return (
    <div className={primary ? "is-primary" : undefined}>
      <strong>{formatCount(value)}</strong>
      <span>{label}</span>
    </div>
  );
}

type ResourceLinksProps =
  | { title: string; references: readonly CharacterReference[]; kind: "character" }
  | { title: string; references: readonly DialogueReference[]; kind: "dialogue" };

export function ResourceLinks(props: ResourceLinksProps) {
  const references = [...props.references].sort((left, right) => (
    left.npcLineCount === right.npcLineCount
      ? left.engineResourceName.localeCompare(right.engineResourceName)
      : left.npcLineCount > right.npcLineCount ? -1 : 1
  ));
  const path = props.kind === "character" ? characterPath : dialoguePath;
  const links = references.map((reference) => ({
    name: reference.name,
    label: `${engineId(reference.engineResourceName)} × ${formatCount(Number(reference.npcLineCount))}`,
    href: path(reference.name),
  }));
  return (
    <section className="resource-links">
      <div className="resource-links-head">
        <h3>{props.title}</h3>
        <span>{formatCount(links.length)}</span>
      </div>
      {links.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <div>
          {links.map((link) => (
            <a key={link.name} href={link.href} onClick={(event) => followLink(event, link.href)}>
              {link.label}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

function engineId(resourceName: string): string {
  return resourceName.replace(/\.(?:CRE|DLG)$/iu, "");
}

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

export function SoundBrowser({ loadPage }: {
  loadPage: (query: ListQuery, signal: AbortSignal) => Promise<ListResult<CharacterSound>>;
}) {
  return (
    <TableBrowser
      loadPage={loadPage}
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
    render: (row) => (
      <a
        className="definition-name resource-title"
        href={dialoguePath(row.dialogue)}
        onClick={(event) => followLink(event, dialoguePath(row.dialogue))}
      >
        <strong className="mono">{resourceId(row.dialogue)}</strong>
        <span>{sourceKindLabel(row.sourceKind)}</span>
      </a>
    ),
  },
  {
    label: "State",
    orderBy: "state_index",
    numeric: true,
    render: (row) => row.stateIndex,
  },
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
  {
    label: "Destination",
    render: (row) => <Destination transition={row} />,
  },
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

export function TransitionBrowser({ loadPage }: {
  loadPage: (query: ListQuery, signal: AbortSignal) => Promise<ListResult<DialogueTransition>>;
}) {
  return (
    <TableBrowser
      defaultOrderBy="location asc"
      loadPage={loadPage}
      columns={TRANSITION_COLUMNS}
      rowKey={(row) => row.name}
      eyebrow="DLG STATE MACHINE"
      title="Dialogue transitions"
      description="Executable dialogue edges with conditions, actions, flags, and destinations."
      noun="transitions"
      searchPlaceholder="Search dialogues, triggers, actions, and destinations…"
      renderFilters={({ value, update }) => (
        <SelectFilter
          label="Destination"
          value={value("terminates_dialog") as "" | "true" | "false"}
          values={BOOLEAN_FILTERS}
          labels={{ true: "Ends dialogue", false: "Continues dialogue" }}
          onChange={(next) => update(
            "terminates_dialog",
            next === "" ? "" : next === "true",
          )}
        />
      )}
      className="transition-browser"
      tableClassName="transition-table"
    />
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
      <strong className="mono">
        {resref}
      </strong>
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

function sourceKindLabel(value: SourceKind): string {
  return SourceKind[value]
    .replace("SOURCE_KIND_", "")
    .replaceAll("_", " ")
    .toLowerCase();
}
