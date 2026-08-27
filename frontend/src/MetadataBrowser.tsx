import { getClasses, getIdentifiers, getKits, getRaces } from "./api";
import {
  FacetFilter,
  SelectFilter,
  TableBrowser,
} from "./browser";
import { formatCount, formatHex } from "./format";
import type {
  ClassQuery,
  ClassRow,
  ClassSort,
  FacetValue,
  IdentifierQuery,
  IdentifierRow,
  IdentifierSort,
  KitQuery,
  KitRow,
  KitSort,
  PaginatedQuery,
  RaceQuery,
  RaceRow,
  RaceSort,
  SimpleIdentifierKind,
} from "./types";
import type { Column, TableBrowserProps } from "./browser";

const BOOLEAN_FILTERS = ["true", "false"] as const;

const DEFAULT_RACE_QUERY: RaceQuery = {
  page: 1,
  page_size: 25,
  q: "",
  sort: "",
  direction: "asc",
  campaign: "",
};

const DEFAULT_CLASS_QUERY: ClassQuery = {
  page: 1,
  page_size: 25,
  q: "",
  sort: "",
  direction: "asc",
  campaign: "",
  fallen: "",
  class_id: "",
};

const DEFAULT_KIT_QUERY: KitQuery = {
  page: 1,
  page_size: 25,
  q: "",
  sort: "",
  direction: "asc",
  class_id: "",
};

const DEFAULT_IDENTIFIER_QUERY: IdentifierQuery = {
  page: 1,
  page_size: 25,
  q: "",
  sort: "",
  direction: "asc",
  kind: "",
};

const RACE_COLUMNS = [
  {
    label: "ID",
    sort: "race_id",
    numeric: true,
    render: (row) => <span className="mono">{row.race_id}</span>,
  },
  {
    label: "Race",
    sort: "name",
    render: (row) => <DefinitionName name={row.name ?? row.row_name} symbols={row.symbols} />,
  },
  {
    label: "Row",
    sort: "row_name",
    render: (row) => <NullableCode value={row.row_name} />,
  },
  {
    label: "Campaigns",
    render: (row) => <Tags values={row.campaigns} />,
  },
  {
    label: "Source",
    sort: "source_resource",
    render: (row) => <SourceCell resource={row.source_resource} ordinal={row.ordinal} />,
  },
  {
    label: "Text",
    render: (row) => (
      <TextDetails
        fields={[
          ["Name", row.name, row.name_strref],
          ["Uppercase", row.uppercase_name, row.uppercase_name_strref],
          ["Description", row.description, row.description_strref],
          ["Biography", row.biography, row.biography_strref],
        ]}
      />
    ),
  },
] satisfies readonly Column<RaceRow, RaceSort>[];

const CLASS_COLUMNS = [
  {
    label: "ID",
    sort: "class_id",
    numeric: true,
    render: (row) => <span className="mono">{row.class_id}</span>,
  },
  {
    label: "Class",
    sort: "lower_name",
    render: (row) => (
      <DefinitionName name={row.mixed_name ?? row.lower_name ?? row.row_name} symbols={row.symbols} />
    ),
  },
  {
    label: "Row",
    sort: "row_name",
    render: (row) => <NullableCode value={row.row_name} />,
  },
  {
    label: "Kit ID",
    numeric: true,
    render: (row) => formatCount(row.class_text_kit_id),
  },
  {
    label: "Campaigns",
    render: (row) => <Tags values={row.campaigns} />,
  },
  {
    label: "Source",
    render: (row) => <SourceCell resource={row.source_resource} ordinal={row.ordinal} />,
  },
  {
    label: "Fallen",
    sort: "fallen",
    render: (row) => row.fallen == null ? "—" : row.fallen ? "Yes" : "No",
  },
  {
    label: "Text",
    render: (row) => (
      <TextDetails
        fields={[
          ["Lower name", row.lower_name, row.lower_name_strref],
          ["Mixed name", row.mixed_name, row.mixed_name_strref],
          ["Description", row.description, row.description_strref],
          ["Brief description", row.brief_description, row.brief_description_strref],
          ["Biography", row.biography, row.biography_strref],
          ["Fallen notice", row.fallen_notice, row.fallen_notice_strref],
        ]}
      />
    ),
  },
] satisfies readonly Column<ClassRow, ClassSort>[];

const KIT_COLUMNS = [
  {
    label: "Row",
    sort: "row_id",
    numeric: true,
    render: (row) => <span className="mono">{row.row_id}</span>,
  },
  {
    label: "Kit",
    sort: "lower_name",
    render: (row) => (
      <DefinitionName name={row.mixed_name ?? row.lower_name ?? row.row_name} symbols={row.kit_symbols} />
    ),
  },
  {
    label: "Row name",
    sort: "row_name",
    render: (row) => <span className="mono">{row.row_name}</span>,
  },
  {
    label: "Class",
    sort: "class_id",
    render: (row) => <ClassDefinition classId={row.class_id} symbols={row.class_symbols} />,
  },
  {
    label: "KITIDS",
    numeric: true,
    render: (row) => (
      <span className="mono">
        {row.kit_ids_value == null ? "—" : formatHex(row.kit_ids_value)}
      </span>
    ),
  },
  {
    label: "Abilities",
    render: (row) => <NullableCode value={row.abilities_resref} />,
  },
  {
    label: "Source",
    render: (row) => <SourceCell resource={row.source_resource} ordinal={row.ordinal} />,
  },
  {
    label: "Details",
    render: (row) => (
      <TextDetails
        fields={[
          ["Lower name", row.lower_name, row.lower_name_strref],
          ["Mixed name", row.mixed_name, row.mixed_name_strref],
          ["Help", row.help_text, row.help_strref],
          ["Proficiency column", formatNullableNumber(row.proficiency_column)],
          ["Unusable mask", row.unusable_mask == null ? null : formatHex(row.unusable_mask)],
          ["CLASTEXT kit ID", formatNullableNumber(row.class_text_kit_id)],
        ]}
      />
    ),
  },
] satisfies readonly Column<KitRow, KitSort>[];

const IDENTIFIER_COLUMNS = [
  {
    label: "Kind",
    sort: "kind",
    render: (row) => <span className="identifier-kind">{row.kind.replaceAll("_", " ")}</span>,
  },
  {
    label: "Value",
    sort: "value",
    numeric: true,
    render: (row) => (
      <span className="mono identifier-value">{row.value} <small>{formatHex(row.value)}</small></span>
    ),
  },
  {
    label: "Symbols",
    render: (row) => <Tags values={row.symbols} mono />,
  },
  {
    label: "Source",
    sort: "source_resource",
    render: (row) => <NullableCode value={row.source_resource} />,
  },
] satisfies readonly Column<IdentifierRow, IdentifierSort>[];

export function RaceBrowser({ campaigns, active }: {
  campaigns: readonly string[];
  active: boolean;
}) {
  return (
    <MetadataTable
      tab="races"
      active={active}
      defaultQuery={DEFAULT_RACE_QUERY}
      loadPage={getRaces}
      columns={RACE_COLUMNS}
      eyebrow="CAMPAIGN RACE DEFINITIONS"
      title="Races"
      description="Canonical RACE.IDS values enriched with campaign-specific names and text."
      noun="races"
      searchPlaceholder="Search race symbols, names, and descriptions…"
      renderFilters={({ query, update }) => (
        <SelectFilter
          label="Campaign"
          value={query.campaign}
          values={campaigns}
          onChange={(value) => update("campaign", value)}
        />
      )}
      filterValues={(query) => [query.campaign]}
    />
  );
}

export function ClassBrowser({
  campaigns,
  classIds,
  active,
}: {
  campaigns: readonly string[];
  classIds: FacetValue[];
  active: boolean;
}) {
  return (
    <MetadataTable
      tab="classes"
      active={active}
      defaultQuery={DEFAULT_CLASS_QUERY}
      loadPage={getClasses}
      columns={CLASS_COLUMNS}
      eyebrow="CAMPAIGN CLASS DEFINITIONS"
      title="Classes"
      description="CLASS.IDS values joined to localized CLASTEXT definitions."
      noun="classes"
      searchPlaceholder="Search class symbols, names, and descriptions…"
      renderFilters={({ query, update }) => (
        <>
          <SelectFilter
            label="Campaign"
            value={query.campaign}
            values={campaigns}
            onChange={(value) => update("campaign", value)}
          />
          <FacetFilter
            label="Class"
            value={query.class_id}
            values={classIds}
            onChange={(value) => update("class_id", value)}
          />
          <SelectFilter
            label="Fallen"
            value={query.fallen}
            values={BOOLEAN_FILTERS}
            labels={{ true: "Fallen", false: "Not fallen" }}
            onChange={(value) => update("fallen", value)}
          />
        </>
      )}
      filterValues={(query) => [query.campaign, query.class_id, query.fallen]}
    />
  );
}

export function KitBrowser({ classIds, active }: {
  classIds: FacetValue[];
  active: boolean;
}) {
  return (
    <MetadataTable
      tab="kits"
      active={active}
      defaultQuery={DEFAULT_KIT_QUERY}
      loadPage={getKits}
      columns={KIT_COLUMNS}
      eyebrow="KITLIST DEFINITIONS"
      title="Kits"
      description="KITLIST rows joined to class and KIT.IDS symbols with resolved display text."
      noun="kits"
      searchPlaceholder="Search kit names, symbols, and ability tables…"
      renderFilters={({ query, update }) => (
        <FacetFilter
          label="Class"
          value={query.class_id}
          values={classIds}
          onChange={(value) => update("class_id", value)}
        />
      )}
      filterValues={(query) => [query.class_id]}
    />
  );
}

export function IdentifierBrowser({ kinds, active }: {
  kinds: readonly SimpleIdentifierKind[];
  active: boolean;
}) {
  return (
    <MetadataTable
      tab="identifiers"
      active={active}
      defaultQuery={DEFAULT_IDENTIFIER_QUERY}
      loadPage={getIdentifiers}
      columns={IDENTIFIER_COLUMNS}
      eyebrow="CRE IDENTIFIER DEFINITIONS"
      title="Identifiers"
      description="Canonical IDS definitions across every extracted CRE metadata category."
      noun="identifiers"
      searchPlaceholder="Search identifier symbols and source resources…"
      renderFilters={({ query, update }) => (
        <SelectFilter
          label="Kind"
          value={query.kind}
          values={kinds}
          labels={{ enemy_ally: "Enemy / ally" }}
          onChange={(value) => update("kind", value)}
        />
      )}
      filterValues={(query) => [query.kind]}
    />
  );
}

function MetadataTable<
  Row extends { key: string },
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>(props: Omit<TableBrowserProps<Row, Sort, Query>, "rowKey" | "className" | "tableClassName">) {
  return (
    <TableBrowser
      {...props}
      rowKey={(row) => row.key}
      className="metadata-browser"
      tableClassName="metadata-table"
    />
  );
}

function DefinitionName({ name, symbols }: { name: string | null; symbols: string[] }) {
  return (
    <div className="definition-name">
      <strong>{name ?? symbols[0] ?? "Unnamed"}</strong>
      {symbols.length > 0 && <span className="mono">{symbols.join(", ")}</span>}
    </div>
  );
}

function ClassDefinition({ classId, symbols }: { classId: number | null; symbols: string[] }) {
  const [primary, ...aliases] = symbols;
  return (
    <div className="definition-name">
      <strong>
        {primary == null
          ? classId == null ? "Unassigned class" : `Class ${classId}`
          : prettifySymbol(primary)}
      </strong>
      <span className="mono">
        ID {formatCount(classId)}{aliases.length === 0 ? "" : ` · ${aliases.join(", ")}`}
      </span>
    </div>
  );
}

function NullableCode({ value }: { value: string | null }) {
  return value == null ? <span className="muted">—</span> : <span className="mono">{value}</span>;
}

function SourceCell({ resource, ordinal }: { resource: string | null; ordinal: number | null }) {
  return (
    <div className="definition-name">
      <NullableCode value={resource} />
      {ordinal != null && <span>Row {ordinal}</span>}
    </div>
  );
}

function Tags({ values, mono = false }: { values: string[]; mono?: boolean }) {
  if (values.length === 0) return <span className="muted">—</span>;
  return (
    <div className="definition-tags">
      {values.map((value) => (
        <span key={value} className={mono ? "mono" : undefined}>{value}</span>
      ))}
    </div>
  );
}

function TextDetails({
  fields,
}: {
  fields: ReadonlyArray<readonly [string, string | null, (number | null)?]>;
}) {
  const available = fields.filter(([, value, strref]) => value != null || strref != null);
  if (available.length === 0) return <span className="muted">No text</span>;
  return (
    <details className="metadata-details">
      <summary>Read</summary>
      <dl>
        {available.map(([label, value, strref]) => (
          <div key={label}>
            <dt>{label}{strref == null ? "" : ` · #${strref}`}</dt>
            <dd>{value ?? <span className="muted">Unresolved</span>}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function formatNullableNumber(value: number | null): string | null {
  return value == null ? null : String(value);
}

function prettifySymbol(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
