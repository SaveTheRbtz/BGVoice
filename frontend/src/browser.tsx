import type { ReactNode } from "react";

import { formatCount } from "./format";
import type {
  FacetValue,
  Page,
  PaginatedQuery,
  SortDirection,
} from "./types";
import { countFilters, useBrowser } from "./browser-state";
import type { BrowserTab } from "./browser-state";

const PAGE_SIZES = [10, 25, 50, 100] as const;

export interface Column<Row, Sort extends string> {
  label: string;
  sort?: Sort;
  numeric?: boolean;
  render: (row: Row) => ReactNode;
}

interface FilterControls<Query> {
  query: Query;
  update: <Key extends keyof Query>(key: Key, value: Query[Key]) => void;
}

export interface TableBrowserProps<
  Row,
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
> {
  defaultQuery: Query;
  tab: BrowserTab;
  active: boolean;
  loadPage: (query: Query, signal: AbortSignal) => Promise<Page<Row, Sort>>;
  columns: readonly Column<Row, Sort>[];
  rowKey: (row: Row) => string;
  eyebrow: string;
  title: string;
  description: string;
  noun: string;
  searchPlaceholder: string;
  renderFilters: (controls: FilterControls<Query>) => ReactNode;
  filterValues: (query: Query) => string[];
  className?: string;
  tableClassName?: string;
}

export function TableBrowser<
  Row,
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>({
  defaultQuery,
  tab,
  active,
  loadPage,
  columns,
  rowKey,
  eyebrow,
  title,
  description,
  noun,
  searchPlaceholder,
  renderFilters,
  filterValues,
  className = "",
  tableClassName = "",
}: TableBrowserProps<Row, Sort, Query>) {
  const browser = useBrowser(tab, active, defaultQuery, loadPage);
  const { query, page, loading } = browser;
  const activeFilters = countFilters(browser.search, ...filterValues(query));

  return (
    <section className={`browser-card tab-panel ${className}`}>
      <BrowserHeading
        eyebrow={eyebrow}
        title={title}
        description={description}
        loading={loading}
        count={page.total}
        noun={noun}
      />
      {browser.error != null && <ErrorBanner message={browser.error} />}
      <div className="toolbar">
        <SearchBox
          value={browser.search}
          onChange={browser.setSearch}
          placeholder={searchPlaceholder}
          label={`Full-text search ${noun}`}
        />
        <RelevanceButton
          visible={browser.search.trim().length > 0}
          active={query.sort === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <div className="filters" aria-label={`${title} filters`}>
        {renderFilters({ query, update: browser.update })}
        {activeFilters > 0 && (
          <button className="clear-filters" type="button" onClick={browser.reset}>
            Clear {activeFilters}
          </button>
        )}
      </div>
      <div className={`table-wrap ${tableClassName} ${loading ? "is-loading" : ""}`}>
        <table>
          <thead>
            <tr>
              {columns.map((column) => column.sort == null ? (
                <th key={column.label} className={column.numeric ? "numeric" : undefined}>
                  {column.label}
                </th>
              ) : (
                <SortHeader
                  key={column.label}
                  label={column.label}
                  sort={column.sort}
                  query={page}
                  onSort={browser.sortBy}
                  numeric={column.numeric}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {page.items.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) => (
                  <td key={column.label} className={column.numeric ? "numeric" : undefined}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
            {!loading && page.items.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={columns.length}>
                  No {noun} match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        loading={loading}
        label={`${title} table pagination`}
        onPageChange={browser.goToPage}
        onPageSizeChange={(size) => browser.update("page_size", size)}
      />
    </section>
  );
}

export function RelevanceButton({ visible, active, onClick }: {
  visible: boolean;
  active: boolean;
  onClick: () => void;
}) {
  if (!visible) return null;
  return (
    <button
      className="relevance-sort"
      type="button"
      aria-pressed={active}
      onClick={onClick}
    >
      Relevance
    </button>
  );
}

export function BrowserHeading({ eyebrow, title, description, loading, count, noun }: {
  eyebrow: string;
  title: string;
  description: string;
  loading: boolean;
  count: number;
  noun: string;
}) {
  return (
    <div className="section-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <ResultCount loading={loading} count={count} noun={noun} />
    </div>
  );
}

export function SearchBox({ value, onChange, placeholder, label }: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
}) {
  return (
    <label className="search-box">
      <span aria-hidden="true">⌕</span>
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
      />
    </label>
  );
}

export function ResultCount({ loading, count, noun }: {
  loading: boolean;
  count: number;
  noun: string;
}) {
  return (
    <div className="result-count" aria-live="polite">
      {loading ? "Loading…" : `${formatCount(count)} ${noun}`}
    </div>
  );
}

export function SortHeader<Sort extends string>({ label, sort, query, onSort, numeric = false }: {
  label: string;
  sort: Sort;
  query: { sort: Sort | "relevance"; direction: SortDirection };
  onSort: (sort: Sort) => void;
  numeric?: boolean;
}) {
  const active = query.sort === sort;
  const direction = query.direction === "asc" ? "ascending" : "descending";
  return (
    <th className={numeric ? "numeric" : undefined} aria-sort={active ? direction : "none"}>
      <button type="button" onClick={() => onSort(sort)}>
        {label}<span>{active ? (query.direction === "asc" ? "↑" : "↓") : "↕"}</span>
      </button>
    </th>
  );
}

export function SelectFilter<Value extends string>({ label, value, values, labels = {}, onChange }: {
  label: string;
  value: "" | Value;
  values: readonly Value[];
  labels?: Partial<Record<Value, string>>;
  onChange: (value: "" | Value) => void;
}) {
  return (
    <label className="filter">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as "" | Value)}
      >
        <option value="">All</option>
        {values.map((item) => (
          <option key={item} value={item}>{labels[item] ?? item}</option>
        ))}
      </select>
    </label>
  );
}

export function FacetFilter<Value extends string>({ label, value, values, onChange }: {
  label: string;
  value: "" | Value;
  values?: FacetValue[];
  onChange: (value: "" | Value) => void;
}) {
  return (
    <label className="filter">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as "" | Value)}
      >
        <option value="">All</option>
        {values?.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label ?? item.value} [{item.value}] · {formatCount(item.count)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Pagination({ page, loading, label, onPageChange, onPageSizeChange }: {
  page: Page<unknown, string>;
  label: string;
  loading: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  const start = page.items.length === 0 ? 0 : (page.page - 1) * page.page_size + 1;
  const end = (page.page - 1) * page.page_size + page.items.length;
  return (
    <div className="pagination" aria-busy={loading}>
      <div>
        <label>
          Rows
          <select
            value={page.page_size}
            disabled={loading}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
          >
            {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <span>{formatCount(start)}–{formatCount(end)} of {formatCount(page.total)}</span>
      </div>
      <nav aria-label={label}>
        <button type="button" onClick={() => onPageChange(1)} disabled={loading || page.page <= 1}>«</button>
        <button type="button" onClick={() => onPageChange(page.page - 1)} disabled={loading || page.page <= 1}>‹</button>
        <span>Page <strong>{page.page}</strong> of {page.page_count}</span>
        <button type="button" onClick={() => onPageChange(page.page + 1)} disabled={loading || page.page >= page.page_count}>›</button>
        <button type="button" onClick={() => onPageChange(page.page_count)} disabled={loading || page.page >= page.page_count}>»</button>
      </nav>
    </div>
  );
}

export function ErrorBanner({ message, onDismiss }: {
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <div className="error-banner" role="alert">
      {onDismiss != null && <strong>Couldn’t refresh the database view.</strong>}
      {onDismiss != null && " "}{message}
      {onDismiss != null && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">×</button>
      )}
    </div>
  );
}
