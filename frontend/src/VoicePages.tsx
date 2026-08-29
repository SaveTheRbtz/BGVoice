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
import { useBrowser } from "./use-browser";
import { useResource } from "./use-resource";

const DEFAULT_ORDER = "npc_line_count desc";
const RELATED_PREVIEW_SIZE = 10;

export function VoiceBrowser() {
  const browser = useBrowser<Voice>(DEFAULT_ORDER, listVoices);
  const { query, result, loading } = browser;
  const search = listSearch(query, DEFAULT_ORDER);

  return (
    <section className="voice-page">
      <BrowserHeading
        eyebrow="VOICE LIBRARY"
        title="Voices"
        description="Find reusable voices and compare their source dialogue, directed text, and generated audio inventories."
        loading={loading}
        count={Number(result.totalSize)}
        noun="voices"
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <VoiceToolbar browser={browser} />
      <VoiceList browser={browser} search={search} />
    </section>
  );
}

function VoiceToolbar({ browser }: {
  browser: ReturnType<typeof useBrowser<Voice>>;
}) {
  return (
    <div className="toolbar voice-toolbar">
      <SearchBox
        value={browser.search}
        onChange={browser.setSearch}
        placeholder="Search voices, characters, and dialogues…"
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
          <option value={DEFAULT_ORDER}>NPC occurrences</option>
          <option value="display_name asc">Name</option>
          <option value="character_count desc">Characters</option>
          <option value="dialogue_count desc">Dialogues</option>
        </select>
      </label>
    </div>
  );
}

function VoiceList({ browser, search }: {
  browser: ReturnType<typeof useBrowser<Voice>>;
  search: string;
}) {
  const { query, result, loading } = browser;
  return (
    <div className="voice-browser">
      <div className={`voice-library ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        <div className="voice-library-head" aria-hidden="true">
          <span>Voice</span>
          <span>Status</span>
          <span className="voice-library-metric-head">
            <span>NPC occurrences</span>
            <span>Directed texts</span>
            <span>Audio samples</span>
          </span>
        </div>
        <div className="voice-list">
          {result.items.map((voice) => <VoiceRow key={voice.name} voice={voice} search={search} />)}
          {!loading && result.items.length === 0 && (
            <div className="voice-empty">No voices match this search.</div>
          )}
        </div>
      </div>
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

function VoiceRow({ voice, search }: { voice: Voice; search: string }) {
  const href = voicePath(voice.name, search);
  const ready = voice.generatedVoice != null;
  const status = ready ? "ready" : "pending";
  const accessibilityLabel = [
    voice.displayName,
    status,
    `${formatCount(Number(voice.npcLineCount))} NPC occurrences`,
    `${formatCount(Number(voice.directedLineCount))} directed texts`,
    `${formatCount(Number(voice.generatedAudioCount))} audio samples`,
  ].join(", ");
  return (
    <a
      className="voice-row"
      href={href}
      aria-label={accessibilityLabel}
      onClick={(event) => followLink(event, href)}
    >
      <VoiceAvatar voice={voice} size="small" />
      <span className="voice-row-copy">
        <strong>{voice.displayName}</strong>
        <span>{voice.generatedVoice?.description ?? voice.prompt}</span>
      </span>
      <span className={`status-pill status-${ready ? "complete" : "pending"}`}>
        {status}
      </span>
      <span className="voice-row-metrics">
        <VoiceRowMetric label="NPC occurrences" value={Number(voice.npcLineCount)} />
        <VoiceRowMetric label="Directed texts" value={Number(voice.directedLineCount)} />
        <VoiceRowMetric label="Audio samples" value={Number(voice.generatedAudioCount)} />
      </span>
      <span className="voice-row-arrow" aria-hidden="true">→</span>
    </a>
  );
}

function VoiceRowMetric({ label, value }: { label: string; value: number }) {
  return (
    <span className="voice-row-metric">
      <small>{label}</small>
      <strong>{formatCount(value)}</strong>
    </span>
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

export function VoiceDetailPage({ name }: { name: string }) {
  const { value: voice, error } = useResource(name, getVoice);
  const listHref = voicePath(undefined, window.location.search);
  return (
    <article className="detail-page voice-detail-page">
      <a className="back-link" href={listHref} onClick={(event) => followLink(event, listHref)}>
        <span aria-hidden="true">←</span> Back to voices
      </a>
      {error != null && <ErrorBanner message={error} />}
      {voice == null && error == null && <p className="detail-loading">Loading voice…</p>}
      {voice != null && <VoiceDetail voice={voice} />}
    </article>
  );
}

function VoiceDetail({ voice }: { voice: Voice }) {
  const ready = voice.generatedVoice != null;
  return (
    <>
      <header className="voice-detail-hero">
        <VoiceAvatar voice={voice} />
        <div className="voice-detail-identity">
          <p className="eyebrow">CANONICAL VOICE</p>
          <div>
            <h1>{voice.displayName}</h1>
            <span className={`status-pill status-${ready ? "complete" : "pending"}`}>
              {ready ? "ready" : "pending"}
            </span>
          </div>
          <span className="resource-name">Resource {resourceId(voice.name)}</span>
          {voice.voiceId !== resourceId(voice.name) && (
            <span className="resource-name">Pipeline ID {voice.voiceId}</span>
          )}
        </div>
      </header>
      <VoiceLineLinks voice={voice} />
      <div className="voice-metrics" aria-label="Voice inventory">
        <VoiceMetric label="NPC occurrences" value={Number(voice.npcLineCount)} />
        <VoiceMetric label="Directed texts" value={Number(voice.directedLineCount)} />
        <VoiceMetric label="Audio samples" value={Number(voice.generatedAudioCount)} primary />
        <VoiceMetric label="Characters" value={voice.characters.length} />
        <VoiceMetric label="Dialogues" value={voice.dialogues.length} />
      </div>
      <div className="voice-dossier">
        <VoiceGeneration voice={voice} />
        <VoiceSource voice={voice} />
      </div>
      <div className="voice-resources">
        <ResourceLinks title="Characters" references={voice.characters} kind="character" />
        <ResourceLinks title="Dialogues" references={voice.dialogues} kind="dialogue" />
      </div>
    </>
  );
}

function VoiceLineLinks({ voice }: { voice: Voice }) {
  const common = { voice_id: voice.voiceId, line_kind: "npc" };
  const links = [
    ["Review audio", dialogueLinesPath({ ...common, voiced: true })],
    ["Needs audio", dialogueLinesPath({ ...common, directed: true, voiced: false })],
    ["All NPC lines", dialogueLinesPath(common)],
    ["Directed lines", dialogueLinesPath({ ...common, directed: true })],
  ] as const;
  return (
    <nav className="generation-links voice-actions" aria-label={`${voice.displayName} dialogue lines`}>
      {links.map(([label, href]) => (
        <a key={label} href={href} onClick={(event) => followLink(event, href)}>{label}</a>
      ))}
    </nav>
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

function VoiceGeneration({ voice }: { voice: Voice }) {
  const generated = voice.generatedVoice;
  return (
    <section className="generation-card">
      <div className="generation-card-head">
        <div>
          <p className="eyebrow">GENERATED VOICE DESIGN</p>
          <h2>{generated == null ? "Not created" : generated.languageCode}</h2>
        </div>
        <span className={`status-pill status-${generated == null ? "pending" : "complete"}`}>
          {generated == null ? "pending" : "ready"}
        </span>
      </div>
      {generated == null ? (
        <p className="muted">No reusable Inworld voice has been created yet.</p>
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

function VoiceSource({ voice }: { voice: Voice }) {
  return (
    <section className="prompt-card">
      <div>
        <p className="eyebrow">SOURCE EVIDENCE</p>
        <span>
          {voice.biography == null
            ? "Current character metadata"
            : `Includes ${resourceId(voice.biography)}`}
        </span>
      </div>
      <h2>Voice prompt</h2>
      <p>{voice.prompt}</p>
    </section>
  );
}

type ResourceLinksProps =
  | { title: string; references: readonly CharacterReference[]; kind: "character" }
  | { title: string; references: readonly DialogueReference[]; kind: "dialogue" };

function ResourceLinks(props: ResourceLinksProps) {
  const references = [...props.references].sort(byLineCount);
  const visible = references.slice(0, RELATED_PREVIEW_SIZE);
  const remaining = references.slice(RELATED_PREVIEW_SIZE);
  return (
    <section className="resource-links">
      <div className="resource-links-head">
        <h2>{props.title}</h2>
        <span>{formatCount(references.length)}</span>
      </div>
      {references.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <>
          <ResourceLinkList references={visible} kind={props.kind} />
          {remaining.length > 0 && (
            <details className="resource-links-more">
              <summary>Show remaining {formatCount(remaining.length)}</summary>
              <ResourceLinkList references={remaining} kind={props.kind} />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function ResourceLinkList({ references, kind }: {
  references: readonly (CharacterReference | DialogueReference)[];
  kind: "character" | "dialogue";
}) {
  const path = kind === "character" ? characterPath : dialoguePath;
  return (
    <div className="resource-link-list">
      {references.map((reference) => {
        const engineName = reference.engineResourceName.replace(/\.(?:CRE|DLG)$/iu, "");
        const label = `${engineName} × ${formatCount(Number(reference.npcLineCount))}`;
        const href = path(reference.name);
        return (
          <a
            key={reference.name}
            href={href}
            aria-label={label}
            onClick={(event) => followLink(event, href)}
          >
            <span className="mono">{engineName}</span>{" "}
            <span>× {formatCount(Number(reference.npcLineCount))}</span>
          </a>
        );
      })}
    </div>
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
