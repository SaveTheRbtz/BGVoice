import { useEffect, useState } from "react";
import type { Timestamp } from "@bufbuild/protobuf/wkt";

import { pipelineData, portraitUrl } from "./api";
import {
  BrowserHeading,
  CursorPagination,
  ErrorBanner,
  NumberFilter,
  RelevanceButton,
  SearchBox,
  SelectFilter,
  SortHeader,
  TableBrowser,
} from "./browser";
import type { Column } from "./browser";
import {
  characterPath,
  dialoguePath,
  errorMessage,
  filterValue,
  followLink,
  navigate,
  resourceId,
  useBrowser,
  useRoute,
  voicePath,
} from "./browser-state";
import { formatBytes, formatCount, formatDate, formatHex } from "./format";
import {
  AttributionStatus,
  DetailStatus,
  DialogueLineKind,
  RunKind,
  RunStatus,
  SourceKind,
  View,
} from "./gen/bgvoice/v1/pipeline_pb";
import type {
  Character,
  Dialogue,
  ExtractionRun,
  Installation,
} from "./gen/bgvoice/v1/pipeline_pb";
import {
  ClassBrowser,
  IdentifierBrowser,
  KitBrowser,
  RaceBrowser,
} from "./MetadataBrowser";
import {
  SoundBrowser,
  TransitionBrowser,
  VoiceBrowser,
} from "./PipelineBrowsers";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const DETAIL_FILTERS = ["pending", "complete", "failed"] as const;
const ATTRIBUTION_FILTERS = [
  "matched",
  "partial_match",
  "missing_dialogue",
  "no_dialogue",
  "character_unavailable",
] as const;
const BOOLEAN_FILTERS = ["true", "false"] as const;

const listVoices = (...args: Parameters<typeof pipelineData.listVoices>) => (
  pipelineData.listVoices(...args)
);
const getVoice = (...args: Parameters<typeof pipelineData.getVoice>) => (
  pipelineData.getVoice(...args)
);
const listCharacters: typeof pipelineData.listCharacters = (query, signal) => (
  pipelineData.listCharacters({ ...query, view: View.FULL }, signal)
);
const getCharacter = (...args: Parameters<typeof pipelineData.getCharacter>) => (
  pipelineData.getCharacter(...args)
);
const listDialogues: typeof pipelineData.listDialogues = (query, signal) => (
  pipelineData.listDialogues({ ...query, view: View.FULL }, signal)
);
const getDialogue = (...args: Parameters<typeof pipelineData.getDialogue>) => (
  pipelineData.getDialogue(...args)
);
const listDialogueLines = (...args: Parameters<typeof pipelineData.listDialogueLines>) => (
  pipelineData.listDialogueLines(...args)
);
const listCharacterSounds = (...args: Parameters<typeof pipelineData.listCharacterSounds>) => (
  pipelineData.listCharacterSounds(...args)
);
const listDialogueTransitions = (...args: Parameters<typeof pipelineData.listDialogueTransitions>) => (
  pipelineData.listDialogueTransitions(...args)
);
const listRaces: typeof pipelineData.listRaces = (query, signal) => (
  pipelineData.listRaces({ ...query, view: View.FULL }, signal)
);
const listCharacterClasses: typeof pipelineData.listCharacterClasses = (query, signal) => (
  pipelineData.listCharacterClasses({ ...query, view: View.FULL }, signal)
);
const listKits = (...args: Parameters<typeof pipelineData.listKits>) => (
  pipelineData.listKits(...args)
);
const listIdentifierDefinitions = (
  ...args: Parameters<typeof pipelineData.listIdentifierDefinitions>
) => pipelineData.listIdentifierDefinitions(...args);
const listExtractionRuns = (...args: Parameters<typeof pipelineData.listExtractionRuns>) => (
  pipelineData.listExtractionRuns(...args)
);

const NAVIGATION = [
  {
    label: "Work",
    links: [{ href: "/voices", label: "Voices", icon: "V", routes: ["voices"] }],
  },
  {
    label: "Dialogue",
    links: [
      { href: "/dialogues", label: "Dialogues", icon: "D", routes: ["dialogues"] },
      { href: "/dialogue-lines", label: "Lines", icon: "L", routes: ["dialogue-lines"] },
      { href: "/dialogue-transitions", label: "Transitions", icon: "T", routes: ["dialogue-transitions"] },
    ],
  },
  {
    label: "Source data",
    links: [
      { href: "/characters", label: "Characters", icon: "C", routes: ["characters"] },
      { href: "/character-sounds", label: "Sounds", icon: "S", routes: ["character-sounds"] },
    ],
  },
  {
    label: "Definitions",
    links: [
      { href: "/definitions/races", label: "Races", icon: "R", routes: ["races"] },
      { href: "/definitions/character-classes", label: "Classes", icon: "C", routes: ["character-classes"] },
      { href: "/definitions/kits", label: "Kits", icon: "K", routes: ["kits"] },
      { href: "/definitions/identifier-definitions", label: "Identifiers", icon: "I", routes: ["identifier-definitions"] },
    ],
  },
  {
    label: "System",
    links: [{ href: "/pipeline", label: "Pipeline", icon: "P", routes: ["pipeline"] }],
  },
] as const;

export default function App() {
  const route = useRoute();
  const [installation, setInstallation] = useState<Installation | null>(null);
  const [installationError, setInstallationError] = useState<string | null>(null);

  useEffect(() => {
    if (window.location.pathname === "/") navigate("/voices", true);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    pipelineData.getInstallation(controller.signal)
      .then(setInstallation)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setInstallationError(errorMessage(reason));
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="app-shell">
      <aside className="side-nav">
        <Brand />
        <nav aria-label="Pipeline resources">
          {NAVIGATION.map((group) => (
            <section className="nav-group" key={group.label}>
              <h2>{group.label}</h2>
              {group.links.map((link) => {
                const active = link.routes.some((name) => name === route.name);
                return (
                  <a
                    key={link.href}
                    className={active ? "is-active" : undefined}
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    onClick={(event) => followLink(event, link.href)}
                  >
                    <span aria-hidden="true">{link.icon}</span>
                    {link.label}
                  </a>
                );
              })}
            </section>
          ))}
        </nav>
        <div className="database-status">
          <span><i /> Read only</span>
          <strong>{installation?.displayName ?? "EET installation"}</strong>
          <small>{formatBytes(toNumber(installation?.databaseSize))}</small>
        </div>
      </aside>

      <header className="mobile-topbar">
        <div className="mobile-topbar-head">
          <Brand />
          <span className="read-only"><i /> Read only</span>
        </div>
        <nav className="mobile-nav" aria-label="Pipeline resources">
          {NAVIGATION.map((group) => group.links.map((link) => {
              const active = link.routes.some((name) => name === route.name);
              return (
                <a
                  key={link.href}
                  className={active ? "is-active" : undefined}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  onClick={(event) => followLink(event, link.href)}
                >
                  {link.label}
                </a>
              );
            }))}
        </nav>
      </header>

      <main className="page-main">
        {installationError != null && <ErrorBanner message={installationError} />}
        <RouteContent route={route} installation={installation} />
      </main>
    </div>
  );
}

function Brand() {
  return (
    <a className="brand-lockup" href="/voices" onClick={(event) => followLink(event, "/voices")}>
      <span className="brand-mark" aria-hidden="true">B</span>
      <span>
        <strong>BGVOICE</strong>
        <small>EET voice pipeline</small>
      </span>
    </a>
  );
}

function RouteContent({ route, installation }: {
  route: ReturnType<typeof useRoute>;
  installation: Installation | null;
}) {
  switch (route.name) {
    case "voices":
      return (
        <VoiceBrowser
          voiceId={route.voiceId}
          loadVoices={listVoices}
          loadVoice={getVoice}
        />
      );
    case "characters":
      return route.resourceName == null
        ? <CharacterBrowser />
        : <CharacterDetailPage name={route.resourceName} />;
    case "dialogues":
      return route.resourceName == null
        ? <DialogueBrowser />
        : <DialogueDetailPage name={route.resourceName} />;
    case "dialogue-lines": return <LineBrowser />;
    case "dialogue-transitions": return <TransitionBrowser loadPage={listDialogueTransitions} />;
    case "character-sounds": return <SoundBrowser loadPage={listCharacterSounds} />;
    case "races": return <RaceBrowser loadPage={listRaces} />;
    case "character-classes": return <ClassBrowser loadPage={listCharacterClasses} />;
    case "kits": return <KitBrowser loadPage={listKits} />;
    case "identifier-definitions": {
      return <IdentifierBrowser loadPage={listIdentifierDefinitions} />;
    }
    case "pipeline": return <PipelinePage installation={installation} />;
    case "not-found": return <NotFound />;
  }
}

type CharacterOrder =
  | "display_name"
  | "engine_resource_name"
  | "source_kind"
  | "serialized_size"
  | "dialogue_line_count"
  | "npc_line_count"
  | "player_line_count"
  | "state_count"
  | "transition_count";

const CHARACTER_COLUMNS = [
  {
    label: "Character",
    orderBy: "display_name",
    render: (character) => (
      <ResourceTitle
        href={characterPath(character.name)}
        title={character.displayName ?? character.resref}
        subtitle={character.engineResourceName}
      />
    ),
  },
  {
    label: "Voice",
    render: (character) => <VoiceLink voice={character.voice} />,
  },
  {
    label: "Source",
    orderBy: "source_kind",
    render: (character) => <SourceBadge kind={character.source?.kind} />,
  },
  {
    label: "Gender",
    render: (character) => <DefinitionValue label={character.detail?.genderLabel} id={character.detail?.genderId} />,
  },
  {
    label: "Race",
    render: (character) => <DefinitionValue label={character.detail?.raceLabel} id={character.detail?.raceId} />,
  },
  {
    label: "Class / kit",
    render: (character) => (
      <div className="stacked-values">
        <DefinitionValue label={character.detail?.classLabel} id={character.detail?.classId} />
        {character.detail?.kitIdsValue != null && (
          <DefinitionValue label={character.detail.kitLabel} id={character.detail.kitIdsValue} secondary />
        )}
      </div>
    ),
  },
  {
    label: "DLGs",
    numeric: true,
    render: (character) => (
      <strong>{formatCount(character.dialogue?.resolvedDialogueCount)} / {formatCount(character.dialogue?.declaredDialogueCount)}</strong>
    ),
  },
  {
    label: "NPC lines",
    orderBy: "npc_line_count",
    numeric: true,
    render: (character) => formatCount(toNumber(character.dialogue?.npcLineCount)),
  },
  {
    label: "Player",
    orderBy: "player_line_count",
    numeric: true,
    render: (character) => formatCount(toNumber(character.dialogue?.playerLineCount)),
  },
  {
    label: "States",
    orderBy: "state_count",
    numeric: true,
    render: (character) => formatCount(toNumber(character.dialogue?.stateCount)),
  },
  {
    label: "Transitions",
    orderBy: "transition_count",
    numeric: true,
    render: (character) => formatCount(toNumber(character.dialogue?.transitionCount)),
  },
  {
    label: "Object size",
    orderBy: "serialized_size",
    numeric: true,
    render: (character) => <span className="mono">{formatBytes(toNumber(character.serializedSize))}</span>,
  },
  {
    label: "Status",
    render: (character) => (
      <StatusPill
        value={character.attributionStatus == null
          ? detailStatusLabel(character.extraction?.status)
          : attributionStatusLabel(character.attributionStatus)}
      />
    ),
  },
] satisfies readonly Column<Character, CharacterOrder>[];

function CharacterBrowser() {
  return (
    <TableBrowser
      loadPage={listCharacters}
      columns={CHARACTER_COLUMNS}
      rowKey={(character) => character.name}
      eyebrow="SOURCE DATA"
      title="Characters"
      description="Every effective CRE resource, linked to the canonical voice it contributes to."
      noun="characters"
      searchPlaceholder="Search names, resources, variables, and scripts…"
      renderFilters={({ value, update }) => (
        <>
          <SelectFilter
            label="Status"
            value={value("detail_status") as "" | (typeof DETAIL_FILTERS)[number]}
            values={DETAIL_FILTERS}
            onChange={(next) => update("detail_status", next)}
          />
          <SelectFilter
            label="Source"
            value={value("source_kind") as "" | (typeof SOURCE_FILTERS)[number]}
            values={SOURCE_FILTERS}
            onChange={(next) => update("source_kind", next)}
          />
          <SelectFilter
            label="Attribution"
            value={value("attribution_status") as "" | (typeof ATTRIBUTION_FILTERS)[number]}
            values={ATTRIBUTION_FILTERS}
            labels={{
              partial_match: "Partial match",
              missing_dialogue: "Missing dialogue",
              no_dialogue: "No dialogue",
              character_unavailable: "Unavailable",
            }}
            onChange={(next) => update("attribution_status", next)}
          />
          <NumberFilter label="Gender ID" value={value("gender_id")} onChange={(next) => update("gender_id", next)} />
          <NumberFilter label="Race ID" value={value("race_id")} onChange={(next) => update("race_id", next)} />
          <NumberFilter label="Class ID" value={value("class_id")} onChange={(next) => update("class_id", next)} />
        </>
      )}
      tableClassName="character-table"
    />
  );
}

type DialogueOrder =
  | "engine_resource_name"
  | "source_kind"
  | "serialized_size"
  | "dialogue_line_count"
  | "npc_line_count"
  | "player_line_count"
  | "character_count";

const DIALOGUE_COLUMNS = [
  {
    label: "Dialogue",
    orderBy: "engine_resource_name",
    render: (dialogue) => (
      <ResourceTitle
        href={dialoguePath(dialogue.name)}
        title={dialogue.engineResourceName}
        subtitle={dialogue.source?.path ?? dialogue.name}
      />
    ),
  },
  {
    label: "Source",
    orderBy: "source_kind",
    render: (dialogue) => <SourceBadge kind={dialogue.source?.kind} />,
  },
  {
    label: "Lines",
    orderBy: "dialogue_line_count",
    numeric: true,
    render: (dialogue) => <strong>{formatCount(toNumber(dialogue.detail?.dialogueLineCount))}</strong>,
  },
  {
    label: "NPC",
    orderBy: "npc_line_count",
    numeric: true,
    render: (dialogue) => formatCount(toNumber(dialogue.detail?.npcLineCount)),
  },
  {
    label: "Player",
    orderBy: "player_line_count",
    numeric: true,
    render: (dialogue) => formatCount(toNumber(dialogue.detail?.playerLineCount)),
  },
  {
    label: "Characters",
    orderBy: "character_count",
    numeric: true,
    render: (dialogue) => formatCount(dialogue.characterCount),
  },
  {
    label: "Object size",
    orderBy: "serialized_size",
    numeric: true,
    render: (dialogue) => <span className="mono">{formatBytes(toNumber(dialogue.serializedSize))}</span>,
  },
  {
    label: "Status",
    render: (dialogue) => <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />,
  },
] satisfies readonly Column<Dialogue, DialogueOrder>[];

function DialogueBrowser() {
  return (
    <TableBrowser
      loadPage={listDialogues}
      columns={DIALOGUE_COLUMNS}
      rowKey={(dialogue) => dialogue.name}
      eyebrow="DIALOGUE GRAPH"
      title="Dialogues"
      description="Every effective DLG resource, including dialogues no character currently references."
      noun="dialogues"
      searchPlaceholder="Search dialogue resources and source paths…"
      renderFilters={({ value, update }) => (
        <>
          <SelectFilter
            label="Status"
            value={value("detail_status") as "" | (typeof DETAIL_FILTERS)[number]}
            values={DETAIL_FILTERS}
            onChange={(next) => update("detail_status", next)}
          />
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
        </>
      )}
      tableClassName="dialogue-table"
    />
  );
}

function LineBrowser() {
  const browser = useBrowser("", listDialogueLines);
  const { query, result, loading } = browser;
  const [expandedLine, setExpandedLine] = useState<string | null>(null);

  return (
    <section className="browser-card resource-page">
      <BrowserHeading
        eyebrow="VOICE WORKLOAD"
        title="Dialogue lines"
        description="Resolved NPC, player, and journal text with stable state-machine coordinates."
        loading={loading}
        count={Number(result.totalSize)}
        noun="lines"
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder="Search resolved text and dialogue resources…"
          label="Search dialogue lines"
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.orderBy === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <div className="filters">
        <SelectFilter
          label="Kind"
          value={filterValue(query.filter, "line_kind") as "" | "npc" | "player" | "journal"}
          values={["npc", "player", "journal"]}
          labels={{ npc: "NPC response", player: "Player response", journal: "Journal" }}
          onChange={(next) => browser.updateFilter("line_kind", next)}
        />
        <SelectFilter
          label="Source"
          value={filterValue(query.filter, "source_kind") as "" | (typeof SOURCE_FILTERS)[number]}
          values={SOURCE_FILTERS}
          onChange={(next) => browser.updateFilter("source_kind", next)}
        />
        <SelectFilter
          label="Attribution"
          value={filterValue(query.filter, "attributed") as "" | "true" | "false"}
          values={BOOLEAN_FILTERS}
          labels={{ true: "Attributed", false: "Unattributed" }}
          onChange={(next) => browser.updateFilter("attributed", next === "" ? "" : next === "true")}
        />
        {query.filter !== "" && (
          <button className="clear-filters" type="button" onClick={browser.reset}>Clear filters</button>
        )}
      </div>
      <div className={`table-wrap line-table ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        <table>
          <thead>
            <tr>
              <th>Resolved text</th>
              <SortHeader label="Dialogue" orderBy="dialogue" activeOrderBy={query.orderBy} onSort={browser.sortBy} />
              <SortHeader label="Kind" orderBy="line_kind" activeOrderBy={query.orderBy} onSort={browser.sortBy} />
              <SortHeader label="Strref" orderBy="strref" activeOrderBy={query.orderBy} onSort={browser.sortBy} numeric />
              <SortHeader label="State" orderBy="state_index" activeOrderBy={query.orderBy} onSort={browser.sortBy} numeric />
              <SortHeader label="Transition" orderBy="transition_index" activeOrderBy={query.orderBy} onSort={browser.sortBy} numeric />
              <th>Context</th>
              <th className="numeric">Characters</th>
            </tr>
          </thead>
          <tbody>
            {result.items.map((line) => (
              <tr key={line.name}>
                <td className="line-text">
                  {line.text == null ? <span className="muted">Unresolved strref</span> : (
                    <button
                      type="button"
                      className={`line-text-toggle ${expandedLine === line.name ? "is-expanded" : ""}`}
                      aria-expanded={expandedLine === line.name}
                      onClick={() => setExpandedLine((current) => current === line.name ? null : line.name)}
                    >
                      {line.text}
                    </button>
                  )}
                </td>
                <td>
                  <ResourceTitle
                    href={dialoguePath(line.dialogue)}
                    title={resourceId(line.dialogue)}
                    subtitle={sourceKindLabel(line.sourceKind)}
                  />
                </td>
                <td><span className="line-kind">{lineKindLabel(line.lineKind)}</span></td>
                <td className="numeric mono">{line.strref}</td>
                <td className="numeric">{line.stateIndex}</td>
                <td className="numeric">{formatCount(line.transitionIndex)}</td>
                <td>
                  <LineContext
                    tokens={line.tokens}
                    triggerIndex={line.stateTriggerIndex}
                    triggerText={line.stateTriggerText}
                  />
                </td>
                <td className="numeric">{formatCount(line.characterCount)}</td>
              </tr>
            ))}
            {!loading && result.items.length === 0 && (
              <tr><td className="empty-state" colSpan={8}>No dialogue lines match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <CursorPagination
        pageSize={query.pageSize}
        visibleCount={result.items.length}
        totalSize={Number(result.totalSize)}
        loading={loading}
        hasPrevious={browser.hasPreviousPage}
        hasNext={result.nextPageToken !== ""}
        label="Dialogue line pagination"
        onPrevious={browser.previousPage}
        onNext={browser.nextPage}
        onPageSizeChange={browser.setPageSize}
      />
    </section>
  );
}

export function LineContext({ tokens, triggerIndex, triggerText }: {
  tokens: readonly string[];
  triggerIndex: number | undefined;
  triggerText: string | undefined;
}) {
  if (tokens.length === 0 && triggerIndex == null && triggerText == null) {
    return <span className="muted">—</span>;
  }
  const counts = new Map<string, number>();
  for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
  const context = [...counts].sort(
    ([left, leftCount], [right, rightCount]) => rightCount - leftCount || left.localeCompare(right),
  );
  return (
    <div className="line-context">
      {context.length > 0 && (
        <div className="definition-tags">
          {context.map(([token, count]) => (
            <span key={token}>{token}{count > 1 && `×${count}`}</span>
          ))}
        </div>
      )}
      {triggerText != null && (
        <details className="table-text-details script-text">
          <summary>State trigger{triggerIndex == null ? "" : ` ${triggerIndex}`}</summary>
          <code>{triggerText}</code>
        </details>
      )}
      {triggerText == null && triggerIndex != null && (
        <span className="muted">State trigger {triggerIndex} · unresolved</span>
      )}
    </div>
  );
}

function CharacterDetailPage({ name }: { name: string }) {
  const resource = useResource(name, getCharacter);
  const character = resource.value;
  const href = "/characters";
  return (
    <section className="detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>← Characters</a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {character == null && resource.error == null ? (
        <div className="detail-loading">Loading character…</div>
      ) : character != null && (
        <>
          <header className="character-profile">
            <ResourceAvatar portrait={character.portrait} label={character.displayName ?? character.resref} />
            <div>
              <p className="eyebrow">CHARACTER RESOURCE</p>
              <h1>{character.displayName ?? character.resref}</h1>
              <span className="resource-name">{character.name}</span>
              <VoiceLink voice={character.voice} />
            </div>
          </header>
          <div className="detail-columns">
            <section className="detail-card">
              <h2>Overview</h2>
              <dl>
                <Data label="Engine resource" value={character.engineResourceName} />
                {character.directDialogue != null && (
                  <ResourceData
                    label="Direct dialogue"
                    name={character.directDialogue}
                    path={dialoguePath}
                  />
                )}
                <Data label="Source" value={sourceKindLabel(character.source?.kind)} />
                <Data
                  label="Biography sound"
                  value={character.biography == null ? "—" : resourceId(character.biography)}
                />
                <Data label="CRE version" value={character.detail?.creVersion ?? "—"} />
                <Data label="Object size" value={formatBytes(toNumber(character.serializedSize))} />
                <Data label="Updated" value={formatTimestamp(character.extraction?.updatedAt)} />
              </dl>
            </section>
            <section className="detail-card">
              <h2>Dialogue workload</h2>
              <div className="metric-grid">
                <Metric label="NPC lines" value={toNumber(character.dialogue?.npcLineCount)} />
                <Metric label="Player lines" value={toNumber(character.dialogue?.playerLineCount)} />
                <Metric label="States" value={toNumber(character.dialogue?.stateCount)} />
                <Metric label="Transitions" value={toNumber(character.dialogue?.transitionCount)} />
              </div>
            </section>
            <section className="detail-card">
              <h2>Classification</h2>
              <dl>
                <Data label="Gender" value={definitionText(character.detail?.genderLabel, character.detail?.genderId)} />
                <Data label="Race" value={definitionText(character.detail?.raceLabel, character.detail?.raceId)} />
                <Data label="Class" value={definitionText(character.detail?.classLabel, character.detail?.classId)} />
                <Data label="Alignment" value={definitionText(character.detail?.alignmentLabel, character.detail?.alignmentId)} />
                <Data label="Kit" value={definitionText(character.detail?.kitLabel, character.detail?.kitIdsValue)} />
                <Data label="Raw CRE kit" value={character.detail == null ? "—" : formatHex(character.detail.creKitValue)} />
              </dl>
            </section>
            <section className="detail-card">
              <h2>Voice signals</h2>
              <div className="metric-grid">
                <Metric label="Strength" value={character.detail?.baseAttributes?.strength} />
                <Metric label="Intelligence" value={character.detail?.baseAttributes?.intelligence} />
                <Metric label="Wisdom" value={character.detail?.baseAttributes?.wisdom} />
                <Metric label="Dexterity" value={character.detail?.baseAttributes?.dexterity} />
                <Metric label="Constitution" value={character.detail?.baseAttributes?.constitution} />
                <Metric label="Charisma" value={character.detail?.baseAttributes?.charisma} />
              </div>
            </section>
          </div>
          <section className="detail-card source-card">
            <h2>Source path</h2>
            <code>{character.source?.path ?? "—"}</code>
          </section>
        </>
      )}
    </section>
  );
}

function DialogueDetailPage({ name }: { name: string }) {
  const resource = useResource(name, getDialogue);
  const dialogue = resource.value;
  const href = "/dialogues";
  return (
    <section className="detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>← Dialogues</a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {dialogue == null && resource.error == null ? (
        <div className="detail-loading">Loading dialogue…</div>
      ) : dialogue != null && (
        <>
          <header className="resource-detail-head">
            <div>
              <p className="eyebrow">DIALOGUE RESOURCE</p>
              <h1>{dialogue.engineResourceName}</h1>
              <span className="resource-name">{dialogue.name}</span>
            </div>
            <StatusPill value={detailStatusLabel(dialogue.extraction?.status)} />
          </header>
          <div className="detail-columns">
            <section className="detail-card">
              <h2>Overview</h2>
              <dl>
                <Data label="Source" value={sourceKindLabel(dialogue.source?.kind)} />
                <Data label="DLG version" value={dialogue.detail?.dlgVersion ?? "—"} />
                <Data label="Object size" value={formatBytes(toNumber(dialogue.serializedSize))} />
                <Data label="Characters" value={formatCount(dialogue.characterCount)} />
                <Data label="Updated" value={formatTimestamp(dialogue.extraction?.updatedAt)} />
                {dialogue.extraction?.error != null && (
                  <Data label="Extraction error" value={dialogue.extraction.error} />
                )}
              </dl>
            </section>
            <section className="detail-card">
              <h2>State machine</h2>
              <div className="metric-grid">
                <Metric label="Lines" value={toNumber(dialogue.detail?.dialogueLineCount)} />
                <Metric label="NPC lines" value={toNumber(dialogue.detail?.npcLineCount)} />
                <Metric label="Player lines" value={toNumber(dialogue.detail?.playerLineCount)} />
                <Metric label="Journal lines" value={toNumber(dialogue.detail?.journalLineCount)} />
                <Metric label="States" value={toNumber(dialogue.detail?.stateCount)} />
                <Metric label="Transitions" value={toNumber(dialogue.detail?.transitionCount)} />
              </div>
            </section>
          </div>
          <section className="detail-card source-card">
            <h2>Source path</h2>
            <code>{dialogue.source?.path ?? "—"}</code>
          </section>
        </>
      )}
    </section>
  );
}

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
  {
    label: "Started",
    orderBy: "started_at",
    render: (run) => formatTimestamp(run.startedAt),
  },
  {
    label: "Completed",
    orderBy: "completed_at",
    render: (run) => formatTimestamp(run.completedAt),
  },
  {
    label: "Extracted",
    numeric: true,
    render: (run) => `${formatCount(toNumber(run.detailsExtracted))} / ${formatCount(toNumber(run.resourcesDiscovered))}`,
  },
  {
    label: "Failures",
    numeric: true,
    render: (run) => formatCount(toNumber(run.failures)),
  },
  {
    label: "Status",
    orderBy: "status",
    render: (run) => <StatusPill value={runStatusLabel(run.status)} />,
  },
] satisfies readonly Column<ExtractionRun, RunOrder>[];

function PipelinePage({ installation }: { installation: Installation | null }) {
  const summary = installation?.summary;
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
        <Stat label="Voices" value={summary?.voices} accent />
        <Stat label="Characters" value={summary?.characters} />
        <Stat label="Dialogues" value={summary?.dialogues} />
        <Stat label="Dialogue lines" value={summary?.dialogueLines} />
        <Stat label="Matched characters" value={summary?.matchedCharacters} />
        <Stat label="Unattributed lines" value={summary?.unattributedDialogueLines} />
      </div>
      <div className="support-stats">
        <SupportStat label="Sounds" value={summary?.characterSounds} />
        <SupportStat label="Transitions" value={summary?.dialogueTransitions} />
        <SupportStat label="Races" value={summary?.races} />
        <SupportStat label="Classes" value={summary?.characterClasses} />
        <SupportStat label="Kits" value={summary?.kits} />
        <SupportStat label="Identifiers" value={summary?.identifierDefinitions} />
      </div>
      <TableBrowser
        defaultOrderBy="started_at desc"
        loadPage={listExtractionRuns}
        columns={RUN_COLUMNS}
        rowKey={(run) => run.name}
        eyebrow="RECENT ACTIVITY"
        title="Extraction runs"
        description="Each independently published stage, newest first."
        noun="runs"
        searchPlaceholder="Search run IDs and stages…"
        className="runs-browser"
      />
    </section>
  );
}

function ResourceTitle({ href, title, subtitle }: {
  href: string;
  title: string;
  subtitle: string;
}) {
  return (
    <a className="resource-title" href={href} onClick={(event) => followLink(event, href)}>
      <strong>{title}</strong>
      <span className="mono">{subtitle}</span>
    </a>
  );
}

export function VoiceLink({ voice }: { voice: string | undefined }) {
  if (voice == null) return <span className="muted">Unassigned</span>;
  const href = voicePath(voice);
  return (
    <a className="voice-link" href={href} onClick={(event) => followLink(event, href)}>
      {resourceId(voice)}
    </a>
  );
}

function ResourceAvatar({ portrait, label }: { portrait: string | undefined; label: string }) {
  return (
    <span className="resource-avatar" aria-label={`${label} portrait`}>
      <span aria-hidden="true">{label.charAt(0).toUpperCase()}</span>
      {portrait != null && (
        <img
          src={portraitUrl(portrait)}
          alt=""
          onError={(event) => { event.currentTarget.hidden = true; }}
        />
      )}
    </span>
  );
}

function DefinitionValue({ label, id, secondary = false }: {
  label: string | undefined;
  id: number | undefined;
  secondary?: boolean;
}) {
  return (
    <span className={`resolved-value ${secondary ? "is-secondary" : ""}`}>
      <strong>{label ?? "Unresolved"}</strong>
      <span className="mono">ID {formatCount(id)}</span>
    </span>
  );
}

function SourceBadge({ kind }: { kind: SourceKind | undefined }) {
  const label = sourceKindLabel(kind);
  return <span className={`source source-${label}`}>{label}</span>;
}

function StatusPill({ value }: { value: string }) {
  return <span className={`status-pill status-${slug(value)}`}>{value}</span>;
}

function Data({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function ResourceData({ label, name, path }: {
  label: string;
  name: string;
  path: (name: string) => string;
}) {
  const href = path(name);
  return (
    <div>
      <dt>{label}</dt>
      <dd><a href={href} onClick={(event) => followLink(event, href)}>{resourceId(name)}</a></dd>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | undefined }) {
  return <div><strong>{formatCount(value)}</strong><span>{label}</span></div>;
}

function Stat({ label, value, accent = false }: {
  label: string;
  value: bigint | undefined;
  accent?: boolean;
}) {
  return (
    <article className={`stat ${accent ? "stat-accent" : ""}`}>
      <span>{label}</span>
      <strong>{formatCount(toNumber(value))}</strong>
    </article>
  );
}

function SupportStat({ label, value }: { label: string; value: bigint | undefined }) {
  return <div><span>{label}</span><strong>{formatCount(toNumber(value))}</strong></div>;
}

function NotFound() {
  const href = "/voices";
  return (
    <section className="not-found">
      <span aria-hidden="true">404</span>
      <h1>Resource not found</h1>
      <p>This route does not identify a pipeline resource.</p>
      <a href={href} onClick={(event) => followLink(event, href)}>Back to voices</a>
    </section>
  );
}

function useResource<Item>(
  name: string,
  load: (name: string, signal?: AbortSignal) => Promise<Item>,
) {
  const [state, setState] = useState<{
    name: string;
    value?: Item;
    error?: string;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    load(name, controller.signal)
      .then((value) => setState({ name, value }))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setState({ name, error: errorMessage(reason) });
        }
      });
    return () => controller.abort();
  }, [load, name]);
  return state?.name === name
    ? { value: state.value ?? null, error: state.error ?? null }
    : { value: null, error: null };
}

function sourceKindLabel(value: SourceKind | undefined): string {
  if (value == null) return "unknown";
  return enumLabel(SourceKind[value], "SOURCE_KIND");
}

function detailStatusLabel(value: DetailStatus | undefined): string {
  if (value == null) return "unknown";
  return enumLabel(DetailStatus[value], "DETAIL_STATUS");
}

function attributionStatusLabel(value: AttributionStatus): string {
  return enumLabel(AttributionStatus[value], "ATTRIBUTION_STATUS");
}

function lineKindLabel(value: DialogueLineKind): string {
  return enumLabel(DialogueLineKind[value], "DIALOGUE_LINE_KIND");
}

function runKindLabel(value: RunKind): string {
  return enumLabel(RunKind[value], "RUN_KIND");
}

function runStatusLabel(value: RunStatus): string {
  return enumLabel(RunStatus[value], "RUN_STATUS");
}

function enumLabel(value: string, prefix: string): string {
  return value
    .replace(`${prefix}_`, "")
    .replaceAll("_", " ")
    .toLowerCase();
}

function definitionText(label: string | undefined, id: number | undefined): string {
  return label == null || id == null ? "—" : `${label} [${id}]`;
}

function slug(value: string): string {
  return value.replaceAll(" ", "-");
}

function toNumber(value: bigint | number | undefined): number | undefined {
  return value == null ? undefined : Number(value);
}

function formatTimestamp(value: Timestamp | undefined): string {
  if (value == null) return "In progress";
  const milliseconds = Number(value.seconds) * 1000 + Math.floor(value.nanos / 1_000_000);
  return formatDate(new Date(milliseconds).toISOString());
}
