import { useEffect, useState } from "react";

import { getVoice, listVoices, portraitUrl } from "./api";
import {
  BrowserHeading,
  CursorPagination,
  ErrorBanner,
  RelevanceButton,
  SearchBox,
} from "./browser";
import { listSearch } from "./filters";
import { formatCount } from "./format";
import type {
  CharacterReference,
  DialogueReference,
  Voice,
} from "./gen/bgvoice/v1/pipeline_pb";
import { formatTimestamp } from "./pipeline-labels";
import {
  characterPath,
  dialoguePath,
  dialogueLinesPath,
  followLink,
  resourceId,
  voicePath,
} from "./routes";
import { errorMessage, useBrowser } from "./use-browser";

export interface VoiceBrowserProps {
  voiceName: string | null;
}

type VoiceDetailState =
  | { name: string; voice: Voice; error?: never }
  | { name: string; voice?: never; error: string };

export function VoiceBrowser({ voiceName }: VoiceBrowserProps) {
  const browser = useBrowser<Voice>("npc_line_count desc", listVoices);
  const { query, result, loading } = browser;
  const listed = voiceName == null
    ? null
    : result.items.find((voice) => voice.name === voiceName) ?? null;
  const selected = useVoiceSelection(voiceName, listed);
  const search = listSearch(query, "npc_line_count desc");

  return (
    <section className="voice-page">
      <BrowserHeading
        eyebrow="VOICE WORKSPACE"
        title="Voices"
        description="Review source identity, generated voice design, direction progress, and audio coverage."
        loading={loading}
        count={Number(result.totalSize)}
        noun="voices"
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <VoiceToolbar browser={browser} />
      <div className="voice-layout">
        <VoiceList browser={browser} selected={selected.voice} search={search} />
        <VoiceDetail
          voice={selected.voice}
          requestedName={voiceName}
          error={selected.error}
          search={search}
        />
      </div>
    </section>
  );
}

function useVoiceSelection(
  voiceName: string | null,
  listed: Voice | null,
): { voice: Voice | null; error: string | null } {
  const [detail, setDetail] = useState<VoiceDetailState | null>(null);
  useEffect(() => {
    if (voiceName == null || listed != null) return undefined;
    const controller = new AbortController();
    getVoice(voiceName, controller.signal)
      .then((voice) => setDetail({ name: voiceName, voice }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setDetail({ name: voiceName, error: errorMessage(reason) });
      });
    return () => controller.abort();
  }, [listed, voiceName]);

  if (listed != null) return { voice: listed, error: null };
  if (detail?.name !== voiceName) return { voice: null, error: null };
  return { voice: detail.voice ?? null, error: detail.error ?? null };
}

function VoiceToolbar({ browser }: {
  browser: ReturnType<typeof useBrowser<Voice>>;
}) {
  return (
    <div className="toolbar voice-toolbar">
      <SearchBox
        value={browser.search}
        onChange={browser.setSearch}
        placeholder="Search names, source metadata, characters, and dialogues…"
        label="Search voices"
      />
      <RelevanceButton
        visible={browser.search.trim().length > 0}
        active={browser.query.orderBy === ""}
        onClick={browser.sortByRelevance}
      />
      <label className="filter voice-order">
        <span>Order</span>
        <select
          value={browser.query.orderBy}
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
  );
}

function VoiceList({ browser, selected, search }: {
  browser: ReturnType<typeof useBrowser<Voice>>;
  selected: Voice | null;
  search: string;
}) {
  const { query, result, loading } = browser;
  return (
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
  );
}

function VoiceCard({ voice, selected, search = "" }: {
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
        <span className="voice-prompt-preview">
          {voice.generatedVoice?.description ?? voice.prompt}
        </span>
        <span className="voice-card-metrics">
          {formatCount(Number(voice.generatedAudioCount))} audio · {formatCount(Number(voice.directedLineCount))} directed · {formatCount(Number(voice.npcLineCount))} source
        </span>
      </span>
    </a>
  );
}

function VoiceAvatar({ voice, size = "large" }: {
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

function VoiceDetail({ voice, requestedName, error, search = "" }: {
  voice: Voice | null;
  requestedName: string | null;
  error: string | null;
  search?: string;
}) {
  if (error != null) {
    return <aside className="voice-detail voice-detail-empty"><ErrorBanner message={error} /></aside>;
  }
  if (voice == null) return <EmptyVoiceDetail loading={requestedName != null} />;
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
        <VoiceMetric label="Source lines" value={Number(voice.npcLineCount)} />
        <VoiceMetric label="Directed" value={Number(voice.directedLineCount)} />
        <VoiceMetric label="Audio" value={Number(voice.generatedAudioCount)} primary />
        <VoiceMetric label="Characters" value={voice.characters.length} />
      </div>
      <VoiceGeneration voice={voice} />
      <section className="prompt-card">
        <div>
          <p className="eyebrow">SOURCE METADATA</p>
          <span>
            {voice.biography == null
              ? "Derived from current character metadata"
              : `Includes ${resourceId(voice.biography)}`}
          </span>
        </div>
        <p>{voice.prompt}</p>
      </section>
      <VoiceLineLinks voice={voice} />
      <ResourceLinks title="Characters" references={voice.characters} kind="character" />
      <ResourceLinks title="Dialogues" references={voice.dialogues} kind="dialogue" />
    </aside>
  );
}

function VoiceGeneration({ voice }: { voice: Voice }) {
  const generated = voice.generatedVoice;
  return (
    <section className="generation-card">
      <div className="generation-card-head">
        <div>
          <p className="eyebrow">GENERATED VOICE</p>
          <h3>{generated == null ? "Not created" : generated.languageCode}</h3>
        </div>
        <span className={`status-pill status-${generated == null ? "pending" : "complete"}`}>
          {generated == null ? "pending" : "ready"}
        </span>
      </div>
      {generated == null ? (
        <p className="muted">Run voice generation to create the reusable Inworld voice.</p>
      ) : (
        <>
          <p>{generated.description}</p>
          <dl>
            <dt>Inworld voice ID</dt>
            <dd className="mono">{generated.inworldVoiceId}</dd>
            <dt>Created</dt>
            <dd>{formatTimestamp(generated.createdAt)}</dd>
          </dl>
        </>
      )}
    </section>
  );
}

function VoiceLineLinks({ voice }: { voice: Voice }) {
  const common = { voice_id: voice.voiceId, line_kind: "npc" };
  const links = [
    ["All source lines", dialogueLinesPath(common)],
    ["Directed", dialogueLinesPath({ ...common, directed: true })],
    ["With audio", dialogueLinesPath({ ...common, voiced: true })],
    ["Needs audio", dialogueLinesPath({ ...common, directed: true, voiced: false })],
  ] as const;
  return (
    <nav className="generation-links" aria-label={`${voice.displayName} dialogue lines`}>
      {links.map(([label, href]) => (
        <a key={label} href={href} onClick={(event) => followLink(event, href)}>{label}</a>
      ))}
    </nav>
  );
}

function EmptyVoiceDetail({ loading }: { loading: boolean }) {
  return (
    <aside className="voice-detail voice-detail-empty">
      <div className="voice-detail-placeholder" aria-hidden="true">♪</div>
      <h2>{loading ? "Loading voice…" : "Choose a voice"}</h2>
      <p>Select a character voice to inspect its prompt and source resources.</p>
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

function ResourceLinks(props: ResourceLinksProps) {
  const references = [...props.references].sort(byLineCount);
  const path = props.kind === "character" ? characterPath : dialoguePath;
  const links = references.map((reference) => ({
    name: reference.name,
    label: `${reference.engineResourceName.replace(/\.(?:CRE|DLG)$/iu, "")} × ${formatCount(Number(reference.npcLineCount))}`,
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

function byLineCount(
  left: CharacterReference | DialogueReference,
  right: CharacterReference | DialogueReference,
): number {
  if (left.npcLineCount === right.npcLineCount) {
    return left.engineResourceName.localeCompare(right.engineResourceName);
  }
  return left.npcLineCount > right.npcLineCount ? -1 : 1;
}
