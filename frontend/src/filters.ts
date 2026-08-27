export const PAGE_SIZES = [10, 25, 50, 100] as const;

export interface BrowserQuery {
  filter: string;
  orderBy: string;
  pageSize: number;
  pageToken: string;
}

export type FilterScalar = string | number | boolean;

interface FilterParts {
  search: string;
  exact: Map<string, FilterScalar>;
}

const DEFAULT_PAGE_SIZE = 25;

export function listQuery(
  search: string = window.location.search,
  defaultOrderBy = "",
): BrowserQuery {
  const parameters = new URLSearchParams(search);
  const requestedSize = Number(parameters.get("page_size"));
  const filter = parameters.get("filter") ?? "";
  const requestedOrder = parameters.get("order_by");
  return {
    filter,
    orderBy: requestedOrder ?? (filterSearch(filter) === "" ? defaultOrderBy : ""),
    pageSize: PAGE_SIZES.includes(requestedSize as (typeof PAGE_SIZES)[number])
      ? requestedSize
      : DEFAULT_PAGE_SIZE,
    pageToken: parameters.get("page_token") ?? "",
  };
}

export function listSearch(query: BrowserQuery, defaultOrderBy = ""): string {
  const parameters = new URLSearchParams();
  setParameter(parameters, "filter", query.filter);
  setParameter(parameters, "order_by", query.orderBy === defaultOrderBy ? "" : query.orderBy);
  setParameter(
    parameters,
    "page_size",
    query.pageSize === DEFAULT_PAGE_SIZE ? "" : String(query.pageSize),
  );
  setParameter(parameters, "page_token", query.pageToken);
  const serialized = parameters.toString();
  return serialized === "" ? "" : `?${serialized}`;
}

function setParameter(parameters: URLSearchParams, name: string, value: string): void {
  if (value !== "") parameters.set(name, value);
}

export function filterSearch(filter: string): string {
  return parseFilter(filter).search;
}

export function filterValue(filter: string, field: string): string {
  const value = parseFilter(filter).exact.get(field);
  return value == null ? "" : String(value);
}

export function setFilterSearch(filter: string, value: string): string {
  const parts = parseFilter(filter);
  parts.search = value.trim();
  return serializeFilter(parts);
}

export function setExactFilter(filter: string, field: string, value: FilterScalar): string {
  const parts = parseFilter(filter);
  if (value === "") parts.exact.delete(field);
  else parts.exact.set(field, value);
  return serializeFilter(parts);
}

export function countFilters(filter: string): number {
  const parts = parseFilter(filter);
  return Number(parts.search !== "") + parts.exact.size;
}

function parseFilter(filter: string): FilterParts {
  const parts: FilterParts = { search: "", exact: new Map() };
  for (const clause of filter.split(" AND ").filter(Boolean)) parseClause(clause, parts);
  return parts;
}

function parseClause(clause: string, parts: FilterParts): void {
  if (clause.startsWith("search(") && clause.endsWith(")")) {
    parts.search = parseString(clause.slice(7, -1)) ?? parts.search;
    return;
  }
  const separator = clause.indexOf(" = ");
  if (separator < 1) return;
  const value = parseScalar(clause.slice(separator + 3));
  if (value != null) parts.exact.set(clause.slice(0, separator), value);
}

function parseScalar(serialized: string): FilterScalar | null {
  if (serialized === "true") return true;
  if (serialized === "false") return false;
  const numeric = Number(serialized);
  if (serialized !== "" && Number.isFinite(numeric)) return numeric;
  return parseString(serialized);
}

function parseString(serialized: string): string | null {
  try {
    const value: unknown = JSON.parse(serialized);
    return typeof value === "string" ? value : null;
  } catch {
    // The API reports malformed filters; the browser only preserves editable clauses.
    return null;
  }
}

function serializeFilter(parts: FilterParts): string {
  const clauses = parts.search === "" ? [] : [`search(${JSON.stringify(parts.search)})`];
  for (const [field, value] of parts.exact) {
    clauses.push(`${field} = ${typeof value === "string" ? JSON.stringify(value) : value}`);
  }
  return clauses.join(" AND ");
}
