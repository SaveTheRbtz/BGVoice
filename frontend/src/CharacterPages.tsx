import { getCharacter, listCharacters } from "./api";
import { ErrorBanner, NumberFilter, SelectFilter, TableBrowser } from "./browser";
import type { Column, FilterControls } from "./browser";
import { formatBytes, formatCount, formatHex } from "./format";
import type { Character } from "./gen/bgvoice/v1/pipeline_pb";
import {
  attributionStatusLabel,
  definitionText,
  detailStatusLabel,
  formatTimestamp,
  sourceKindLabel,
  toNumber,
} from "./pipeline-labels";
import {
  Data,
  DefinitionValue,
  Metric,
  ResourceAvatar,
  ResourceData,
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
  { label: "Voice", render: (character) => <VoiceLink voice={character.voice} /> },
  {
    label: "Source",
    orderBy: "source_kind",
    render: (character) => <SourceBadge kind={character.source?.kind} />,
  },
  {
    label: "Gender",
    render: (character) => (
      <DefinitionValue label={character.detail?.genderLabel} id={character.detail?.genderId} />
    ),
  },
  {
    label: "Race",
    render: (character) => (
      <DefinitionValue label={character.detail?.raceLabel} id={character.detail?.raceId} />
    ),
  },
  {
    label: "Class / kit",
    render: (character) => <CharacterClass character={character} />,
  },
  {
    label: "DLGs",
    numeric: true,
    render: (character) => (
      <strong>
        {formatCount(character.dialogue?.resolvedDialogueCount)} / {formatCount(character.dialogue?.declaredDialogueCount)}
      </strong>
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
    render: (character) => <CharacterStatus character={character} />,
  },
] satisfies readonly Column<Character, CharacterOrder>[];

export function CharacterBrowser() {
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
      renderFilters={CharacterFilters}
      tableClassName="character-table"
    />
  );
}

function CharacterClass({ character }: { character: Character }) {
  const detail = character.detail;
  return (
    <div className="stacked-values">
      <DefinitionValue label={detail?.classLabel} id={detail?.classId} />
      {detail?.kitIdsValue != null && (
        <DefinitionValue label={detail.kitLabel} id={detail.kitIdsValue} secondary />
      )}
    </div>
  );
}

function CharacterStatus({ character }: { character: Character }) {
  const value = character.attributionStatus == null
    ? detailStatusLabel(character.extraction?.status)
    : attributionStatusLabel(character.attributionStatus);
  return <StatusPill value={value} />;
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
      <NumberFilter label="Gender ID" value={value("gender_id")} onChange={(next) => update("gender_id", next)} />
      <NumberFilter label="Race ID" value={value("race_id")} onChange={(next) => update("race_id", next)} />
      <NumberFilter label="Class ID" value={value("class_id")} onChange={(next) => update("class_id", next)} />
    </>
  );
}

export function CharacterDetailPage({ name }: { name: string }) {
  const resource = useResource(name, getCharacter);
  const href = "/characters";
  return (
    <section className="detail-page">
      <a className="back-link" href={href} onClick={(event) => followLink(event, href)}>← Characters</a>
      {resource.error != null && <ErrorBanner message={resource.error} />}
      {resource.value == null && resource.error == null && (
        <div className="detail-loading">Loading character…</div>
      )}
      {resource.value != null && <CharacterDetail character={resource.value} />}
    </section>
  );
}

function CharacterDetail({ character }: { character: Character }) {
  return (
    <>
      <CharacterHeader character={character} />
      <div className="detail-columns">
        <CharacterOverview character={character} />
        <CharacterWorkload character={character} />
        <CharacterClassification character={character} />
        <CharacterAttributes character={character} />
      </div>
      <section className="detail-card source-card">
        <h2>Source path</h2>
        <code>{character.source?.path ?? "—"}</code>
      </section>
    </>
  );
}

function CharacterHeader({ character }: { character: Character }) {
  const label = character.displayName ?? character.resref;
  return (
    <header className="character-profile">
      <ResourceAvatar portrait={character.portrait} label={label} />
      <div>
        <p className="eyebrow">CHARACTER RESOURCE</p>
        <h1>{label}</h1>
        <span className="resource-name">{character.name}</span>
        <VoiceLink voice={character.voice} />
      </div>
    </header>
  );
}

function CharacterOverview({ character }: { character: Character }) {
  return (
    <section className="detail-card">
      <h2>Overview</h2>
      <dl>
        <Data label="Engine resource" value={character.engineResourceName} />
        {character.directDialogue != null && (
          <ResourceData label="Direct dialogue" name={character.directDialogue} path={dialoguePath} />
        )}
        <Data label="Source" value={sourceKindLabel(character.source?.kind)} />
        <Data label="Biography sound" value={character.biography == null ? "—" : resourceId(character.biography)} />
        <Data label="CRE version" value={character.detail?.creVersion ?? "—"} />
        <Data label="Object size" value={formatBytes(toNumber(character.serializedSize))} />
        <Data label="Updated" value={formatTimestamp(character.extraction?.updatedAt)} />
      </dl>
    </section>
  );
}

function CharacterWorkload({ character }: { character: Character }) {
  const dialogue = character.dialogue;
  return (
    <section className="detail-card">
      <h2>Dialogue workload</h2>
      <div className="metric-grid">
        <Metric label="NPC lines" value={toNumber(dialogue?.npcLineCount)} />
        <Metric label="Player lines" value={toNumber(dialogue?.playerLineCount)} />
        <Metric label="States" value={toNumber(dialogue?.stateCount)} />
        <Metric label="Transitions" value={toNumber(dialogue?.transitionCount)} />
      </div>
    </section>
  );
}

function CharacterClassification({ character }: { character: Character }) {
  const {
    genderLabel,
    genderId,
    raceLabel,
    raceId,
    classLabel,
    classId,
    alignmentLabel,
    alignmentId,
    kitLabel,
    kitIdsValue,
    creKitValue,
  } = character.detail ?? {};
  return (
    <section className="detail-card">
      <h2>Classification</h2>
      <dl>
        <Data label="Gender" value={definitionText(genderLabel, genderId)} />
        <Data label="Race" value={definitionText(raceLabel, raceId)} />
        <Data label="Class" value={definitionText(classLabel, classId)} />
        <Data label="Alignment" value={definitionText(alignmentLabel, alignmentId)} />
        <Data label="Kit" value={definitionText(kitLabel, kitIdsValue)} />
        <Data label="Raw CRE kit" value={creKitValue == null ? "—" : formatHex(creKitValue)} />
      </dl>
    </section>
  );
}

function CharacterAttributes({ character }: { character: Character }) {
  const {
    strength,
    intelligence,
    wisdom,
    dexterity,
    constitution,
    charisma,
  } = character.detail?.baseAttributes ?? {};
  return (
    <section className="detail-card">
      <h2>Voice signals</h2>
      <div className="metric-grid">
        <Metric label="Strength" value={strength} />
        <Metric label="Intelligence" value={intelligence} />
        <Metric label="Wisdom" value={wisdom} />
        <Metric label="Dexterity" value={dexterity} />
        <Metric label="Constitution" value={constitution} />
        <Metric label="Charisma" value={charisma} />
      </div>
    </section>
  );
}
