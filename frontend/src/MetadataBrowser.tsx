import { Fragment } from "react";
import type { ReactNode } from "react";

import {
  listCharacterClasses,
  listIdentifierDefinitions,
  listKits,
  listRaces,
} from "./api";
import {
  BrowserScaffold,
  NumberFilter,
  OrderSelect,
  SelectFilter,
  TableBrowser,
  TextFilter,
} from "./browser";
import type { Column, FilterControls, OrderOption } from "./browser";
import { formatCount, formatHex } from "./format";
import { IdentifierKind } from "./gen/bgvoice/v1/pipeline_pb";
import type {
  CharacterClass,
  CharacterClassText,
  IdentifierDefinition,
  Kit,
  Race,
  RaceText,
} from "./gen/bgvoice/v1/pipeline_pb";
import { useBrowser } from "./use-browser";

const BOOLEAN_FILTERS = ["true", "false"] as const;
const IDENTIFIER_KINDS = [
  "gender",
  "alignment",
  "enemy_ally",
  "general",
  "specific",
  "animation",
  "sound_slot",
] as const;

type IdentifierOrder = "kind" | "value" | "display_name" | "source_resource";

const RACE_ORDERS = [
  { value: "race_id asc", label: "Engine ID" },
  { value: "display_name asc", label: "Name" },
] satisfies readonly OrderOption[];

const CLASS_ORDERS = [
  { value: "class_id asc", label: "Engine ID" },
  { value: "display_name asc", label: "Name" },
] satisfies readonly OrderOption[];

const KIT_ORDERS = [
  { value: "row_id asc", label: "KITLIST row" },
  { value: "display_name asc", label: "Name" },
  { value: "character_class asc", label: "Class" },
] satisfies readonly OrderOption[];

const IDENTIFIER_COLUMNS = [
  {
    label: "Kind",
    orderBy: "kind",
    render: (definition) => (
      <span className="identifier-kind">{identifierKindLabel(definition.kind)}</span>
    ),
  },
  {
    label: "Value",
    orderBy: "value",
    numeric: true,
    render: (definition) => (
      <span className="mono identifier-value">
        {definition.value} <small>{formatHex(definition.value)}</small>
      </span>
    ),
  },
  {
    label: "Definition",
    orderBy: "display_name",
    render: (definition) => (
      <span className="identifier-definition">
        <strong>{definition.displayName}</strong>
        <span className="mono">{definition.symbols.join(" · ")}</span>
      </span>
    ),
  },
  {
    label: "Source",
    orderBy: "source_resource",
    render: (definition) => <span className="mono">{definition.sourceResource}</span>,
  },
] satisfies readonly Column<IdentifierDefinition, IdentifierOrder>[];

export function RaceBrowser() {
  const browser = useBrowser("race_id asc", listRaces);
  return (
    <DefinitionCatalog
      browser={browser}
      title="Races"
      description="Canonical RACE.IDS values with every campaign-specific name, description, and biography."
      noun="races"
      searchPlaceholder="Search race symbols, names, and descriptions…"
      orderOptions={RACE_ORDERS}
      renderFilters={RaceFilters}
      renderItem={(race) => <RaceDefinition race={race} />}
    />
  );
}

export function ClassBrowser() {
  const browser = useBrowser("class_id asc", listCharacterClasses);
  return (
    <DefinitionCatalog
      browser={browser}
      title="Character classes"
      description="CLASS.IDS definitions joined to every localized CLASTEXT variant."
      noun="classes"
      searchPlaceholder="Search class symbols, names, and descriptions…"
      orderOptions={CLASS_ORDERS}
      renderFilters={ClassFilters}
      renderItem={(characterClass) => <ClassDefinition characterClass={characterClass} />}
    />
  );
}

export function KitBrowser() {
  const browser = useBrowser("row_id asc", listKits);
  return (
    <DefinitionCatalog
      browser={browser}
      title="Kits"
      description="KITLIST rows joined to their owning class and KIT.IDS symbols."
      noun="kits"
      searchPlaceholder="Search kit names, symbols, and ability tables…"
      orderOptions={KIT_ORDERS}
      renderFilters={KitFilters}
      renderItem={(kit) => <KitDefinition kit={kit} />}
    />
  );
}

export function IdentifierBrowser() {
  return (
    <TableBrowser
      defaultOrderBy="kind asc"
      loadPage={listIdentifierDefinitions}
      columns={IDENTIFIER_COLUMNS}
      rowKey={(definition) => definition.name}
      eyebrow="ENGINE DEFINITIONS"
      title="Identifiers"
      description="Look up readable IDS values used by extracted CRE metadata."
      noun="identifiers"
      searchPlaceholder="Search symbols, values, and source resources…"
      renderFilters={IdentifierFilters}
      tableClassName="identifier-table"
    />
  );
}

function DefinitionCatalog<Row extends { name: string }>({
  browser,
  title,
  description,
  noun,
  searchPlaceholder,
  orderOptions,
  renderFilters,
  renderItem,
}: {
  browser: ReturnType<typeof useBrowser<Row>>;
  title: string;
  description: string;
  noun: string;
  searchPlaceholder: string;
  orderOptions: readonly OrderOption[];
  renderFilters: (controls: FilterControls) => ReactNode;
  renderItem: (row: Row) => ReactNode;
}) {
  const { result, loading } = browser;
  return (
    <BrowserScaffold
      browser={browser}
      eyebrow="ENGINE DEFINITIONS"
      title={title}
      description={description}
      noun={noun}
      searchPlaceholder={searchPlaceholder}
      renderFilters={(controls) => (
        <>
          {renderFilters(controls)}
          <OrderSelect
            value={browser.query.orderBy}
            options={orderOptions}
            onChange={browser.setOrderBy}
          />
        </>
      )}
    >
      <div className={`definition-list ${loading ? "is-loading" : ""}`} aria-busy={loading}>
        {result.items.map((row) => (
          <Fragment key={row.name}>{renderItem(row)}</Fragment>
        ))}
        {!loading && result.items.length === 0 && (
          <div className="empty-state">No {noun} match this filter.</div>
        )}
      </div>
    </BrowserScaffold>
  );
}

function RaceFilters({ value, update }: FilterControls) {
  return (
    <TextFilter
      label="Campaign text"
      value={value("campaign")}
      placeholder="soa"
      onChange={(next) => update("campaign", next)}
    />
  );
}

function ClassFilters({ value, update }: FilterControls) {
  return (
    <>
      <TextFilter
        label="Campaign text"
        value={value("campaign")}
        placeholder="soa"
        onChange={(next) => update("campaign", next)}
      />
      <NumberFilter
        label="Class ID"
        value={value("class_id")}
        onChange={(next) => update("class_id", next)}
      />
      <SelectFilter
        label="Text variant"
        value={value("fallen") as "" | "true" | "false"}
        values={BOOLEAN_FILTERS}
        labels={{ true: "Fallen", false: "Not fallen" }}
        onChange={(next) => update("fallen", next === "" ? "" : next === "true")}
      />
    </>
  );
}

function KitFilters({ value, update }: FilterControls) {
  return (
    <NumberFilter
      label="Class ID"
      value={value("class_id")}
      onChange={(next) => update("class_id", next)}
    />
  );
}

function IdentifierFilters({ value, update }: FilterControls) {
  return (
    <SelectFilter
      label="Kind"
      value={value("kind") as "" | (typeof IDENTIFIER_KINDS)[number]}
      values={IDENTIFIER_KINDS}
      labels={{ enemy_ally: "Enemy / ally", sound_slot: "Sound slot" }}
      onChange={(next) => update("kind", next)}
    />
  );
}

function RaceDefinition({ race }: { race: Race }) {
  return (
    <DefinitionCard
      id={String(race.raceId)}
      name={race.displayName}
      symbols={race.symbols}
      aside={variantLabel(race.texts.length)}
    >
      {race.texts.length > 0 ? (
        <div className="definition-variants">
          {race.texts.map((text) => (
            <RaceTextVariant
              key={`${text.sourceResource}:${text.rowName}`}
              text={text}
            />
          ))}
        </div>
      ) : undefined}
    </DefinitionCard>
  );
}

function RaceTextVariant({ text }: { text: RaceText }) {
  return (
    <section className="definition-variant">
      <VariantHeader title={text.rowName} tags={[...text.campaigns, text.sourceResource]} />
      <dl className="definition-fields">
        <DefinitionField label="Name" value={text.displayName} strref={text.nameStrref} />
        <DefinitionField
          label="Uppercase name"
          value={text.uppercaseName}
          strref={text.uppercaseNameStrref}
        />
        <DefinitionField
          label="Description"
          value={text.description}
          strref={text.descriptionStrref}
        />
        <DefinitionField
          label="Biography"
          value={text.biography}
          strref={text.biographyStrref}
        />
      </dl>
    </section>
  );
}

function ClassDefinition({ characterClass }: { characterClass: CharacterClass }) {
  return (
    <DefinitionCard
      id={String(characterClass.classId)}
      name={characterClass.displayName}
      symbols={characterClass.symbols}
      aside={variantLabel(characterClass.texts.length)}
    >
      {characterClass.texts.length > 0 ? (
        <div className="definition-variants">
          {characterClass.texts.map((text) => (
            <ClassTextVariant
              key={`${text.sourceResource}:${text.rowName}:${text.classTextKitId}`}
              text={text}
            />
          ))}
        </div>
      ) : undefined}
    </DefinitionCard>
  );
}

function ClassTextVariant({ text }: { text: CharacterClassText }) {
  return (
    <section className="definition-variant">
      <VariantHeader
        title={text.rowName}
        tags={[
          ...text.campaigns,
          text.sourceResource,
          `CLASTEXT kit ${text.classTextKitId}`,
          text.fallen ? "Fallen" : "Not fallen",
        ]}
      />
      <dl className="definition-fields">
        <DefinitionField label="Lower name" value={text.lowerName} strref={text.lowerNameStrref} />
        <DefinitionField label="Mixed name" value={text.mixedName} strref={text.mixedNameStrref} />
        <DefinitionField
          label="Description"
          value={text.description}
          strref={text.descriptionStrref}
        />
        <DefinitionField
          label="Brief description"
          value={text.briefDescription}
          strref={text.briefDescriptionStrref}
        />
        <DefinitionField
          label="Biography"
          value={text.biography}
          strref={text.biographyStrref}
        />
        <DefinitionField
          label="Fallen notice"
          value={text.fallenNotice}
          strref={text.fallenNoticeStrref}
        />
      </dl>
    </section>
  );
}

function KitDefinition({ kit }: { kit: Kit }) {
  const className = kit.classSymbols.length === 0
    ? "Unassigned"
    : kit.classSymbols.map((symbol) => symbol.replaceAll("_", " ")).join(" · ");
  return (
    <DefinitionCard
      id={String(kit.rowId)}
      name={kit.displayName}
      symbols={kit.kitSymbols}
      aside={(
        <>
          <strong>{className}</strong>
          <span>{kit.kitIdsValue == null ? "No KITIDS" : formatHex(kit.kitIdsValue)}</span>
        </>
      )}
    >
      <div className="kit-definition-grid">
        <section className="definition-variant">
          <VariantHeader title="Player-facing text" tags={[]} />
          <dl className="definition-fields">
            <DefinitionField label="Lower name" value={kit.lowerName} />
            <DefinitionField label="Mixed name" value={kit.mixedName} />
            <DefinitionField label="Help" value={kit.helpText} />
          </dl>
        </section>
        <section className="definition-variant">
          <VariantHeader title="Engine linkage" tags={[kit.sourceResource]} />
          <dl className="definition-fields definition-engine-fields">
            <DefinitionField label="KITLIST row" value={kit.rowName} />
            <DefinitionField label="Class" value={className} />
            <DefinitionField label="Class resource" value={kit.characterClass} />
            <DefinitionField
              label="KITIDS value"
              value={kit.kitIdsValue == null ? undefined : formatHex(kit.kitIdsValue)}
            />
            <DefinitionField label="Abilities table" value={kit.abilitiesResref} />
            <DefinitionField
              label="Proficiency column"
              value={kit.proficiencyColumn == null ? undefined : String(kit.proficiencyColumn)}
            />
            <DefinitionField
              label="Unusable mask"
              value={kit.unusableMask == null ? undefined : formatHex(kit.unusableMask)}
            />
          </dl>
        </section>
      </div>
    </DefinitionCard>
  );
}

function DefinitionCard({ id, name, symbols, aside, children }: {
  id: string;
  name: string;
  symbols: readonly string[];
  aside: ReactNode;
  children?: ReactNode;
}) {
  const summary = (
    <>
      <span className="definition-card-id mono">{id}</span>
      <span className="definition-card-title">
        <strong>{name}</strong>
        <span className="mono">{symbols.join(" · ") || "No IDS symbol"}</span>
      </span>
      <span className="definition-card-aside">{aside}</span>
    </>
  );
  if (children == null) {
    return (
      <article className="definition-card is-empty">
        <div className="definition-card-summary">{summary}</div>
      </article>
    );
  }
  return (
    <details className="definition-card">
      <summary>{summary}</summary>
      <div className="definition-card-body">{children}</div>
    </details>
  );
}

function VariantHeader({ title, tags }: { title: string; tags: readonly string[] }) {
  return (
    <header className="definition-variant-head">
      <h3>{title}</h3>
      <DefinitionTags values={tags} />
    </header>
  );
}

function DefinitionField({ label, value, strref }: {
  label: string;
  value: string | undefined;
  strref?: number;
}) {
  if (value == null && strref == null) return null;
  return (
    <div>
      <dt>{label}{strref == null ? "" : ` · #${strref}`}</dt>
      <dd>{value ?? <span className="muted">Unresolved</span>}</dd>
    </div>
  );
}

function DefinitionTags({ values }: { values: readonly string[] }) {
  const unique = [...new Set(values.filter(Boolean))];
  if (unique.length === 0) return null;
  return (
    <div className="definition-tags">
      {unique.map((value) => <span key={value}>{value}</span>)}
    </div>
  );
}

function variantLabel(count: number): string {
  return count === 0
    ? "No localized text"
    : `${formatCount(count)} text ${count === 1 ? "variant" : "variants"}`;
}

function identifierKindLabel(value: IdentifierKind): string {
  return IdentifierKind[value]
    .replace("IDENTIFIER_KIND_", "")
    .replaceAll("_", " ")
    .toLowerCase();
}
