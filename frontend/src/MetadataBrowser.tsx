import {
  NumberFilter,
  SelectFilter,
  TableBrowser,
  TextFilter,
} from "./browser";
import type { Column, TableBrowserProps } from "./browser";
import {
  listCharacterClasses,
  listIdentifierDefinitions,
  listKits,
  listRaces,
} from "./api";
import { formatCount, formatHex } from "./format";
import { IdentifierKind } from "./gen/bgvoice/v1/pipeline_pb";
import type {
  CharacterClass,
  IdentifierDefinition,
  Kit,
  Race,
} from "./gen/bgvoice/v1/pipeline_pb";

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

type RaceOrder = "race_id" | "display_name";
type ClassOrder = "class_id" | "display_name";
type KitOrder = "row_id" | "display_name" | "character_class";
type IdentifierOrder = "kind" | "value" | "display_name" | "source_resource";

const RACE_COLUMNS = [
  {
    label: "ID",
    orderBy: "race_id",
    numeric: true,
    render: (race) => <span className="mono">{race.raceId}</span>,
  },
  {
    label: "Race",
    orderBy: "display_name",
    render: (race) => <DefinitionName name={race.displayName} symbols={race.symbols} />,
  },
  {
    label: "Campaign text",
    render: (race) => (
      <TextCollection
        items={race.texts.map((text) => ({
          title: text.rowName ?? text.sourceResource,
          meta: [...text.campaigns, text.sourceResource],
          fields: [
            ["Name", text.displayName, text.nameStrref],
            ["Uppercase", text.uppercaseName, text.uppercaseNameStrref],
            ["Description", text.description, text.descriptionStrref],
            ["Biography", text.biography, text.biographyStrref],
          ],
        }))}
      />
    ),
  },
] satisfies readonly Column<Race, RaceOrder>[];

const CLASS_COLUMNS = [
  {
    label: "ID",
    orderBy: "class_id",
    numeric: true,
    render: (characterClass) => <span className="mono">{characterClass.classId}</span>,
  },
  {
    label: "Class",
    orderBy: "display_name",
    render: (characterClass) => (
      <DefinitionName name={characterClass.displayName} symbols={characterClass.symbols} />
    ),
  },
  {
    label: "Campaign text",
    render: (characterClass) => (
      <TextCollection
        items={characterClass.texts.map((text) => ({
          title: text.rowName ?? text.sourceResource,
          meta: [...text.campaigns, text.sourceResource],
          fields: [
            ["Lower name", text.lowerName, text.lowerNameStrref],
            ["Mixed name", text.mixedName, text.mixedNameStrref],
            ["Description", text.description, text.descriptionStrref],
            ["Brief description", text.briefDescription, text.briefDescriptionStrref],
            ["Biography", text.biography, text.biographyStrref],
            ["Fallen notice", text.fallenNotice, text.fallenNoticeStrref],
          ],
        }))}
      />
    ),
  },
] satisfies readonly Column<CharacterClass, ClassOrder>[];

const KIT_COLUMNS = [
  {
    label: "Row",
    orderBy: "row_id",
    numeric: true,
    render: (kit) => <span className="mono">{kit.rowId}</span>,
  },
  {
    label: "Kit",
    orderBy: "display_name",
    render: (kit) => <DefinitionName name={kit.displayName} symbols={kit.kitSymbols} />,
  },
  {
    label: "Class",
    orderBy: "character_class",
    render: (kit) => (
      <div className="definition-name">
        <strong>{kit.classSymbols[0]?.replaceAll("_", " ") ?? "Unassigned"}</strong>
        {kit.characterClass != null && <span className="mono">{kit.characterClass}</span>}
      </div>
    ),
  },
  {
    label: "KITIDS",
    numeric: true,
    render: (kit) => (
      <span className="mono">
        {kit.kitIdsValue == null ? "—" : formatHex(kit.kitIdsValue)}
      </span>
    ),
  },
  {
    label: "Source",
    render: (kit) => (
      <div className="definition-name">
        <span className="mono">{kit.sourceResource}</span>
        <span>{kit.rowName}</span>
      </div>
    ),
  },
  {
    label: "Details",
    render: (kit) => (
      <TextCollection
        items={[{
          title: kit.displayName,
          meta: [kit.abilitiesResref ?? "No ability table"],
          fields: [
            ["Lower name", kit.lowerName],
            ["Mixed name", kit.mixedName],
            ["Help", kit.helpText],
            ["Proficiency column", kit.proficiencyColumn == null ? undefined : String(kit.proficiencyColumn)],
            ["Unusable mask", kit.unusableMask == null ? undefined : formatHex(kit.unusableMask)],
          ],
        }]}
      />
    ),
  },
] satisfies readonly Column<Kit, KitOrder>[];

const IDENTIFIER_COLUMNS = [
  {
    label: "Kind",
    orderBy: "kind",
    render: (definition) => <span className="identifier-kind">{identifierKindLabel(definition.kind)}</span>,
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
      <DefinitionName name={definition.displayName} symbols={definition.symbols} />
    ),
  },
  {
    label: "Source",
    orderBy: "source_resource",
    render: (definition) => <span className="mono">{definition.sourceResource}</span>,
  },
] satisfies readonly Column<IdentifierDefinition, IdentifierOrder>[];

export function RaceBrowser() {
  return (
    <MetadataTable
      defaultOrderBy="race_id asc"
      loadPage={listRaces}
      columns={RACE_COLUMNS}
      eyebrow="ENGINE DEFINITIONS"
      title="Races"
      description="Canonical RACE.IDS values with every campaign-specific name, description, and biography."
      noun="races"
      searchPlaceholder="Search race symbols, names, and descriptions…"
      renderFilters={({ value, update }) => (
        <TextFilter
          label="Campaign"
          value={value("campaign")}
          placeholder="soa"
          onChange={(next) => update("campaign", next)}
        />
      )}
    />
  );
}

export function ClassBrowser() {
  return (
    <MetadataTable
      defaultOrderBy="class_id asc"
      loadPage={listCharacterClasses}
      columns={CLASS_COLUMNS}
      eyebrow="ENGINE DEFINITIONS"
      title="Character classes"
      description="CLASS.IDS definitions joined to all localized CLASTEXT variants."
      noun="classes"
      searchPlaceholder="Search class symbols, names, and descriptions…"
      renderFilters={({ value, update }) => (
        <>
          <TextFilter
            label="Campaign"
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
            label="Fallen"
            value={value("fallen") as "" | "true" | "false"}
            values={BOOLEAN_FILTERS}
            labels={{ true: "Fallen", false: "Not fallen" }}
            onChange={(next) => update("fallen", next === "" ? "" : next === "true")}
          />
        </>
      )}
    />
  );
}

export function KitBrowser() {
  return (
    <MetadataTable
      defaultOrderBy="row_id asc"
      loadPage={listKits}
      columns={KIT_COLUMNS}
      eyebrow="ENGINE DEFINITIONS"
      title="Kits"
      description="KITLIST rows joined to their class and KIT.IDS symbols."
      noun="kits"
      searchPlaceholder="Search kit names, symbols, and ability tables…"
      renderFilters={({ value, update }) => (
        <NumberFilter
          label="Class ID"
          value={value("class_id")}
          onChange={(next) => update("class_id", next)}
        />
      )}
    />
  );
}

export function IdentifierBrowser() {
  return (
    <MetadataTable
      defaultOrderBy="kind asc"
      loadPage={listIdentifierDefinitions}
      columns={IDENTIFIER_COLUMNS}
      eyebrow="ENGINE DEFINITIONS"
      title="Identifier definitions"
      description="Readable IDS values used by extracted CRE metadata."
      noun="definitions"
      searchPlaceholder="Search symbols and source resources…"
      renderFilters={({ value, update }) => (
        <SelectFilter
          label="Kind"
          value={value("kind") as "" | (typeof IDENTIFIER_KINDS)[number]}
          values={IDENTIFIER_KINDS}
          labels={{ enemy_ally: "Enemy / ally", sound_slot: "Sound slot" }}
          onChange={(next) => update("kind", next)}
        />
      )}
    />
  );
}

function MetadataTable<Row extends { name: string }, Order extends string>(
  props: Omit<TableBrowserProps<Row, Order>, "rowKey" | "className" | "tableClassName">,
) {
  return (
    <TableBrowser
      {...props}
      rowKey={(row) => row.name}
      className="metadata-browser"
      tableClassName="metadata-table"
    />
  );
}

function DefinitionName({ name, symbols }: { name: string; symbols: readonly string[] }) {
  return (
    <div className="definition-name">
      <strong>{name}</strong>
      {symbols.length > 0 && <span className="mono">{symbols.join(", ")}</span>}
    </div>
  );
}

interface TextItem {
  title: string;
  meta: readonly string[];
  fields: ReadonlyArray<readonly [string, string | undefined, (number | undefined)?]>;
}

function TextCollection({ items }: { items: readonly TextItem[] }) {
  if (items.length === 0) return <span className="muted">No localized text</span>;
  return (
    <details className="metadata-details">
      <summary>Read {formatCount(items.length)} {items.length === 1 ? "entry" : "entries"}</summary>
      <div className="metadata-text-list">
        {items.map((item, index) => (
          <section key={`${item.title}:${index}`}>
            <h3>{item.title}</h3>
            <Tags values={item.meta} />
            <dl>
              {item.fields
                .filter(([, value, strref]) => value != null || strref != null)
                .map(([label, value, strref]) => (
                  <div key={label}>
                    <dt>{label}{strref == null ? "" : ` · #${strref}`}</dt>
                    <dd>{value ?? <span className="muted">Unresolved</span>}</dd>
                  </div>
                ))}
            </dl>
          </section>
        ))}
      </div>
    </details>
  );
}

function Tags({ values }: { values: readonly string[] }) {
  const unique = [...new Set(values.filter(Boolean))];
  if (unique.length === 0) return null;
  return (
    <div className="definition-tags">
      {unique.map((value) => <span key={value}>{value}</span>)}
    </div>
  );
}

function identifierKindLabel(value: IdentifierKind): string {
  return IdentifierKind[value]
    .replace("IDENTIFIER_KIND_", "")
    .replaceAll("_", " ")
    .toLowerCase();
}
