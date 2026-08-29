import type { ReactNode } from "react";
import type { ListQuery, ListResult } from "./api";

import { countFilters, filterValue, PAGE_SIZES } from "./filters";
import { formatCount } from "./format";
import { useBrowser } from "./use-browser";

export interface Column<Row, Order extends string> {
  label: string;
  orderBy?: Order;
  numeric?: boolean;
  render: (row: Row) => ReactNode;
}

export interface FilterControls {
  value: (field: string) => string;
  update: (field: string, value: string | number | boolean) => void;
}

export interface TableBrowserProps<Row, Order extends string> {
  defaultOrderBy?: "" | `${Order} asc` | `${Order} desc`;
  loadPage: (query: ListQuery, signal: AbortSignal) => Promise<ListResult<Row>>;
  columns: readonly Column<Row, Order>[];
  rowKey: (row: Row) => string;
  eyebrow: string;
  title: string;
  description: string;
  noun: string;
  searchPlaceholder: string;
  renderFilters?: (controls: FilterControls) => ReactNode;
  className?: string;
  tableClassName?: string;
  headingLevel?: 1 | 2;
}

export interface BrowserScaffoldProps<Row> {
  browser: ReturnType<typeof useBrowser<Row>>;
  eyebrow: string;
  title: string;
  description: string;
  noun: string;
  searchPlaceholder: string;
  renderFilters?: (controls: FilterControls) => ReactNode;
  className?: string;
  headingLevel?: 1 | 2;
  children: ReactNode;
}

export function TableBrowser<Row, Order extends string>({
  defaultOrderBy = "",
  loadPage,
  columns,
  rowKey,
  eyebrow,
  title,
  description,
  noun,
  searchPlaceholder,
  renderFilters,
  className = "",
  tableClassName = "",
  headingLevel = 1,
}: TableBrowserProps<Row, Order>) {
  const browser = useBrowser(defaultOrderBy, loadPage);
  const { query, result, loading } = browser;
  return (
    <BrowserScaffold
      browser={browser}
      eyebrow={eyebrow}
      title={title}
      description={description}
      noun={noun}
      searchPlaceholder={searchPlaceholder}
      renderFilters={renderFilters}
      className={className}
      headingLevel={headingLevel}
    >
      <div
        className={`table-wrap ${tableClassName} ${loading ? "is-loading" : ""}`}
        aria-busy={loading}
      >
        <table>
          <thead>
            <tr>
              {columns.map((column) => column.orderBy == null ? (
                <th key={column.label} className={column.numeric ? "numeric" : undefined}>
                  {column.label}
                </th>
              ) : (
                <SortHeader
                  key={column.label}
                  label={column.label}
                  orderBy={column.orderBy}
                  activeOrderBy={query.orderBy}
                  onSort={browser.sortBy}
                  numeric={column.numeric}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {result.items.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) => (
                  <td key={column.label} className={column.numeric ? "numeric" : undefined}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
            {!loading && result.items.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={columns.length}>
                  No {noun} match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </BrowserScaffold>
  );
}

export function BrowserScaffold<Row>({
  browser,
  eyebrow,
  title,
  description,
  noun,
  searchPlaceholder,
  renderFilters,
  className = "",
  headingLevel = 1,
  children,
}: BrowserScaffoldProps<Row>) {
  const { query, result, loading } = browser;
  const activeFilters = countFilters(query.filter);
  const controls: FilterControls = {
    value: (field) => filterValue(query.filter, field),
    update: browser.updateFilter,
  };

  return (
    <section className={`browser-card resource-page ${className}`}>
      <BrowserHeading
        eyebrow={eyebrow}
        title={title}
        description={description}
        loading={loading}
        count={Number(result.totalSize)}
        noun={noun}
        headingLevel={headingLevel}
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
          active={query.orderBy === ""}
          onClick={browser.sortByRelevance}
        />
      </div>
      <BrowserFilters
        title={title}
        count={activeFilters}
        controls={controls}
        render={renderFilters}
        onClear={browser.reset}
      />
      {children}
      <CursorPagination
        pageSize={query.pageSize}
        visibleCount={result.items.length}
        totalSize={Number(result.totalSize)}
        loading={loading}
        hasPrevious={browser.hasPreviousPage}
        hasNext={result.nextPageToken !== ""}
        label={`${title} pagination`}
        onPrevious={browser.previousPage}
        onNext={browser.nextPage}
        onPageSizeChange={browser.setPageSize}
      />
    </section>
  );
}

function BrowserFilters({ title, count, controls, render, onClear }: {
  title: string;
  count: number;
  controls: FilterControls;
  render: ((controls: FilterControls) => ReactNode) | undefined;
  onClear: () => void;
}) {
  if (render == null && count === 0) return null;
  return (
    <div className="filters" aria-label={`${title} filters`}>
      {render?.(controls)}
      {count > 0 && (
        <button className="clear-filters" type="button" onClick={onClear}>
          Clear {count}
        </button>
      )}
    </div>
  );
}

export function BrowserHeading({
  eyebrow,
  title,
  description,
  loading,
  count,
  noun,
  headingLevel = 1,
}: {
  eyebrow: string;
  title: string;
  description: string;
  loading: boolean;
  count: number;
  noun: string;
  headingLevel?: 1 | 2;
}) {
  return (
    <div className="section-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        {headingLevel === 1 ? <h1>{title}</h1> : <h2>{title}</h2>}
        <p>{description}</p>
      </div>
      <div className="result-count" aria-live="polite">
        {loading ? "Loading…" : `${formatCount(count)} ${count === 1 ? "result" : noun}`}
      </div>
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

export function SortHeader<Order extends string>({
  label,
  orderBy,
  activeOrderBy,
  onSort,
  numeric = false,
}: {
  label: string;
  orderBy: Order;
  activeOrderBy: string;
  onSort: (field: string) => void;
  numeric?: boolean;
}) {
  const [activeField, direction] = activeOrderBy.split(" ");
  const active = activeField === orderBy;
  return (
    <th
      className={numeric ? "numeric" : undefined}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button type="button" onClick={() => onSort(orderBy)}>
        {label}<span>{active ? (direction === "asc" ? "↑" : "↓") : "↕"}</span>
      </button>
    </th>
  );
}

export function SelectFilter<Value extends string>({
  label,
  value,
  values,
  labels = {},
  onChange,
}: {
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

export function TextFilter({ label, value, placeholder, onChange }: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="filter">
      <span>{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function NumberFilter({ label, value, onChange }: {
  label: string;
  value: string;
  onChange: (value: "" | number) => void;
}) {
  return (
    <label className="filter filter-number">
      <span>{label}</span>
      <input
        type="number"
        min="0"
        value={value}
        onChange={(event) => onChange(
          event.target.value === "" ? "" : Number(event.target.value),
        )}
      />
    </label>
  );
}

export function CursorPagination({
  pageSize,
  visibleCount,
  totalSize,
  loading,
  hasPrevious,
  hasNext,
  label,
  onPrevious,
  onNext,
  onPageSizeChange,
}: {
  pageSize: number;
  visibleCount: number;
  totalSize: number;
  loading: boolean;
  hasPrevious: boolean;
  hasNext: boolean;
  label: string;
  onPrevious: () => void;
  onNext: () => void;
  onPageSizeChange: (pageSize: number) => void;
}) {
  return (
    <div className="pagination" aria-busy={loading}>
      <div>
        <label>
          Rows
          <select
            value={pageSize}
            disabled={loading}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
          >
            {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </label>
        <span>{formatCount(visibleCount)} shown · {formatCount(totalSize)} total</span>
      </div>
      <nav aria-label={label}>
        <button type="button" onClick={onPrevious} disabled={loading || !hasPrevious}>
          ← Previous
        </button>
        <button type="button" onClick={onNext} disabled={loading || !hasNext}>
          Next →
        </button>
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
      {message}
      {onDismiss != null && (
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">×</button>
      )}
    </div>
  );
}
