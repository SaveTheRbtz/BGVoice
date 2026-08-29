import { getCharacter, listCharacters } from "./api";
import { ErrorBanner, SelectFilter, TableBrowser } from "./browser";
import type { Column, FilterControls } from "./browser";
import { formatBytes, formatCount, formatHex } from "./format";
import {
  AttributionStatus,
  type Character,
  type CharacterBaseAttributes,
  type CharacterDetail,
} from "./gen/bgvoice/v1/pipeline_pb";
import {
  attributionStatusLabel,
  detailStatusLabel,
  formatTimestamp,
  sourceKindLabel,
  toNumber,
} from "./pipeline-labels";
import {
  Data,
  Metric,
  ResourceAvatar,
  ResourceTitle,
  SourceBadge,
  StatusPill,
  VoiceLink,
} from "./resource-ui";
import { characterPath, dialoguePath, followLink, resourceId } from "./routes";
import { useResource } from "./use-resource";

const SOURCE_FILTERS = ["override", "bif", "dlc"] as const;
const DETAIL_FILTERS = ["pending", "complete", "failed"] as const;
const ATTRIBUTION_FILTERS = [
  "matched",
  "partial_match",
  "missing_dialogue",
  "no_dialogue",
  "character_unavailable",
] as const;

type CharacterOrder = "display_name" | "source_kind" | "npc_line_count";

const CHARACTER_COLUMNS = [
  {
    label: "Character",
    orderBy: "display_name",
    render: (character) => (
      <div className="character-list-identity">
        <ResourceAvatar portrait={character.portrait} label={character.displayName} size="small" />
        <ResourceTitle
          href={characterPath(character.name, window.location.search)}
          title={character.displayName}
          subtitle={character.engineResourceName}
        />
      </div>
    ),
  },
  { label: "Voice", render: (character) => <VoiceLink voice={character.voice} /> },
  {
    label: "Profile",
    render: (character) => {
      const detail = character.detail;
      return (
        <span className="character-list-profile">
          <strong>{detail?.genderLabel || "Unresolved"} · {detail?.raceLabel || "Unresolved"}</strong>
          <span>{detail?.classLabel || "Unresolved"}{detail?.kitLabel == null ? "" : ` · ${detail.kitLabel}`}</span>
        </span>
      );
    },
  },
  {
    label: "Dialogue",
    orderBy: "npc_line_count",
    render: (character) => (
      <span className="character-dialogue-workload">
        <strong>{formatCount(toNumber(character.dialogue?.npcLineCount))} NPC occurrences</strong>
        <span>
          {formatCount(character.dialogue?.resolvedDialogueCount)} of {formatCount(character.dialogue?.declaredDialogueCount)} DLGs resolved
        </span>
      </span>
    ),
  },
  {
    label: "Provenance",
    orderBy: "source_kind",
    render: (character) => (
      <div className="character-provenance">
        <SourceBadge kind={character.source?.kind} />
        <StatusPill value={characterStatus(character)} />
      </div>
    ),
  },
] satisfies readonly Column<Character, CharacterOrder>[];

export function CharacterBrowser() {
  return (
    <TableBrowser
      defaultOrderBy="npc_line_count desc"
      loadPage={listCharacters}
      columns={CHARACTER_COLUMNS}
      rowKey={(character) => character.name}
      eyebrow="SOURCE DATA"
      title="Characters"
      description="Browse effective CRE variants, their canonical voices, profiles, and dialogue attribution."
      noun="characters"
      searchPlaceholder="Search names, CRE resources, variables, and scripts…"
      renderFilters={CharacterFilters}
      tableClassName="character-table"
    />
  );
}

function CharacterFilters({ value, update }: FilterControls) {
  return (
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
    </>
  );
}

function characterStatus(character: Character): string {
  return character.attributionStatus === AttributionStatus.UNSPECIFIED
    ? detailStatusLabel(character.extraction?.status)
    : attributionStatusLabel(character.attributionStatus);
}

export function CharacterDetailPage({ name }: { name: string }) {
  const resource = useResource(name, getCharacter);
  const href = characterPath(undefined, window.location.search);
  return (
    <article className="detail-page character-detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>
        <span aria-hidden="true">←</span> Back to characters
      </a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {resource.value == null && resource.error == null && (
        <p className="detail-loading">Loading character…</p>
      )}
      {resource.value != null && <CharacterDetail character={resource.value} />}
    </article>
  );
}

function CharacterDetail({ character }: { character: Character }) {
  return (
    <>
      <CharacterHeader character={character} />
      <CharacterWorkload character={character} />
      <div className="character-detail-grid">
        <CharacterVoiceProfile character={character} />
        <CharacterResourceDetails character={character} />
      </div>
      <CharacterTechnicalSource character={character} />
    </>
  );
}

function CharacterHeader({ character }: { character: Character }) {
  return (
    <header className="character-profile">
      <ResourceAvatar portrait={character.portrait} label={character.displayName} />
      <div className="character-profile-copy">
        <p className="eyebrow">CHARACTER RESOURCE</p>
        <h1>{character.displayName}</h1>
        <span className="resource-name">
          {character.engineResourceName} · {resourceId(character.name)}
        </span>
        <div className="character-profile-links">
          <span>Voice <VoiceLink voice={character.voice} /></span>
          <SourceBadge kind={character.source?.kind} />
          <StatusPill value={characterStatus(character)} />
        </div>
      </div>
    </header>
  );
}

function CharacterWorkload({ character }: { character: Character }) {
  const dialogue = character.dialogue;
  return (
    <div className="character-metrics" aria-label="Character dialogue workload">
      <CharacterMetric label="NPC lines" value={formatCount(toNumber(dialogue?.npcLineCount))} />
      <CharacterMetric label="Player lines" value={formatCount(toNumber(dialogue?.playerLineCount))} />
      <CharacterMetric
        label="DLGs resolved"
        value={`${formatCount(dialogue?.resolvedDialogueCount)} of ${formatCount(dialogue?.declaredDialogueCount)}`}
      />
      <CharacterMetric label="States" value={formatCount(toNumber(dialogue?.stateCount))} />
      <CharacterMetric label="Transitions" value={formatCount(toNumber(dialogue?.transitionCount))} />
    </div>
  );
}

function CharacterMetric({ label, value }: { label: string; value: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}

function CharacterVoiceProfile({ character }: { character: Character }) {
  return (
    <section className="detail-card character-voice-profile">
      <h2>Voice profile</h2>
      <div className="character-voice-profile-grid">
        <CharacterDefinitions detail={character.detail} />
        <CharacterAbilities attributes={character.detail?.baseAttributes} />
      </div>
    </section>
  );
}

function CharacterDefinitions({ detail }: { detail: CharacterDetail | undefined }) {
  return (
    <dl>
      <Data label="Gender" value={detail?.genderLabel || "Unresolved"} />
      <Data label="Race" value={detail?.raceLabel || "Unresolved"} />
      <Data label="Class" value={detail?.classLabel || "Unresolved"} />
      <Data label="Kit" value={detail?.kitLabel ?? "No kit"} />
      <Data label="Alignment" value={detail?.alignmentLabel || "Unresolved"} />
    </dl>
  );
}

function CharacterAbilities({ attributes }: { attributes: CharacterBaseAttributes | undefined }) {
  return (
    <div className="character-abilities">
      <h3>Ability scores</h3>
      <div className="metric-grid">
        <Metric label="Strength" value={attributes?.strength} />
        <Metric label="Intelligence" value={attributes?.intelligence} />
        <Metric label="Wisdom" value={attributes?.wisdom} />
        <Metric label="Dexterity" value={attributes?.dexterity} />
        <Metric label="Constitution" value={attributes?.constitution} />
        <Metric label="Charisma" value={attributes?.charisma} />
      </div>
    </div>
  );
}

function CharacterResourceDetails({ character }: { character: Character }) {
  const dialogueHref = character.directDialogue == null ? null : dialoguePath(character.directDialogue);
  const dialogueLabel = character.detail?.dialogResref == null
    ? character.directDialogue == null ? "—" : resourceId(character.directDialogue)
    : `${character.detail.dialogResref.toUpperCase()}.DLG`;
  return (
    <section className="detail-card character-resource-details">
      <h2>Resource details</h2>
      <dl>
        <div>
          <dt>Direct dialogue</dt>
          <dd>
            {dialogueHref == null ? "—" : (
              <a href={dialogueHref} onClick={(event) => followLink(event, dialogueHref)}>
                {dialogueLabel}
              </a>
            )}
          </dd>
        </div>
        <Data label="Biography sound" value={character.biography == null ? "—" : resourceId(character.biography)} />
        <Data label="Source" value={sourceKindLabel(character.source?.kind)} />
        <Data label="CRE version" value={character.detail?.creVersion || "—"} />
        <Data label="Object size" value={formatBytes(toNumber(character.serializedSize))} />
        <Data label="Updated" value={formatTimestamp(character.extraction?.updatedAt)} />
        {character.extraction?.error != null && (
          <Data label="Extraction error" value={character.extraction.error} />
        )}
      </dl>
    </section>
  );
}

function CharacterTechnicalSource({ character }: { character: Character }) {
  return (
    <details className="technical-source">
      <summary>Technical source</summary>
      <dl>
        <Data label="Canonical resource" value={resourceId(character.name)} />
        <Data
          label="Raw CRE kit"
          value={character.detail == null ? "—" : formatHex(character.detail.creKitValue)}
        />
      </dl>
      <code>{character.source?.path ?? "—"}</code>
    </details>
  );
}
