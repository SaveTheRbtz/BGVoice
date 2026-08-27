import { useEffect, useRef, useState } from "react";

import type { Page, PaginatedQuery } from "./types";

export const BROWSER_TABS = [
  "characters",
  "dialogues",
  "lines",
  "voices",
  "transitions",
  "races",
  "classes",
  "kits",
  "identifiers",
] as const;

export type BrowserTab = (typeof BROWSER_TABS)[number];

const savedSearches = new Map<BrowserTab, string>();

export function browserTab(search: string = window.location.search): BrowserTab {
  const value = new URLSearchParams(search).get("tab");
  return BROWSER_TABS.find((tab) => tab === value) ?? "characters";
}

export function browserQuery<
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>(defaults: Query, search: string): Query {
  const parameters = new URLSearchParams(search);
  const restored = { ...defaults };
  for (const key of Object.keys(defaults) as Array<keyof Query>) {
    const value = parameters.get(String(key));
    if (value == null) continue;
    const fallback = defaults[key];
    if (typeof fallback === "number") {
      const parsed = Number(value);
      if (Number.isInteger(parsed) && parsed > 0) {
        restored[key] = parsed as Query[typeof key];
      }
    } else {
      restored[key] = value as Query[typeof key];
    }
  }
  return restored;
}

export function browserSearch<
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>(tab: BrowserTab, query: Query, defaults: Query): string {
  const parameters = new URLSearchParams({ tab });
  for (const key of Object.keys(defaults) as Array<keyof Query>) {
    const value = query[key];
    if (value !== "" && value !== defaults[key]) {
      parameters.set(String(key), String(value));
    }
  }
  return `?${parameters.toString()}`;
}

export function navigateToTab(tab: BrowserTab): void {
  const url = new URL(window.location.href);
  url.search = savedSearches.get(tab) ?? `?tab=${tab}`;
  window.history.pushState(null, "", url);
}

function initialQuery<Sort extends string, Query extends PaginatedQuery<Sort>>(
  tab: BrowserTab,
  defaults: Query,
): Query {
  const search = browserTab() === tab
    ? window.location.search
    : savedSearches.get(tab) ?? "";
  return browserQuery(defaults, search);
}

export function useBrowser<
  Item,
  Sort extends string,
  Query extends PaginatedQuery<Sort>,
>(
  tab: BrowserTab,
  active: boolean,
  defaultQuery: Query,
  loadPage: (query: Query, signal: AbortSignal) => Promise<Page<Item, Sort>>,
) {
  const [query, setQuery] = useState(() => initialQuery(tab, defaultQuery));
  const [search, setSearch] = useState(query.q);
  const [page, setPage] = useState<Page<Item, Sort>>(() => ({
    items: [],
    page: 1,
    page_size: defaultQuery.page_size,
    total: 0,
    page_count: 1,
    sort: "relevance",
    direction: defaultQuery.direction,
  }));
  const [loadedQuery, setLoadedQuery] = useState<Query | null>(null);
  const [error, setError] = useState<string | null>(null);
  const restoring = useRef(false);
  const queryRef = useRef(query);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  useEffect(() => {
    if (!active) return undefined;

    const restore = () => {
      if (browserTab() !== tab) return;
      const next = browserQuery(defaultQuery, window.location.search);
      savedSearches.set(tab, browserSearch(tab, next, defaultQuery));
      if (
        (Object.keys(defaultQuery) as Array<keyof Query>)
          .some((key) => queryRef.current[key] !== next[key])
      ) {
        restoring.current = true;
        setQuery(next);
        setSearch(next.q);
      }
    };

    restore();
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [active, defaultQuery, tab]);

  useEffect(() => {
    const nextSearch = browserSearch(tab, query, defaultQuery);
    savedSearches.set(tab, nextSearch);
    if (!active || browserTab() !== tab) return;
    if (restoring.current) {
      restoring.current = false;
      return;
    }
    const url = new URL(window.location.href);
    url.search = nextSearch;
    window.history.replaceState(null, "", url);
  }, [active, defaultQuery, query, tab]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const q = search.trim();
      setQuery((current) =>
        current.q === q ? current : { ...current, q, page: 1 },
      );
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    loadPage(query, controller.signal)
      .then((result) => {
        setPage(result);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedQuery(query);
      });
    return () => controller.abort();
  }, [loadPage, query]);

  function update<Key extends keyof Query>(key: Key, value: Query[Key]) {
    setQuery((current) => ({ ...current, [key]: value, page: 1 }));
  }

  function sortBy(sort: Sort) {
    setQuery((current) => ({
      ...current,
      page: 1,
      sort,
      direction:
        page.sort === sort && page.direction === "desc" ? "asc" : "desc",
    }));
  }

  function sortByRelevance() {
    setQuery((current) => ({
      ...current,
      page: 1,
      sort: "",
      direction: defaultQuery.direction,
    }));
  }

  function reset() {
    setSearch("");
    setQuery((current) => ({
      ...defaultQuery,
      page_size: current.page_size,
    }));
  }

  function goToPage(nextPage: number) {
    setQuery((current) => ({
      ...current,
      page: Math.max(1, Math.min(page.page_count, nextPage)),
    }));
  }

  return {
    query,
    search,
    setSearch,
    page,
    loading: loadedQuery !== query,
    error,
    update,
    sortBy,
    sortByRelevance,
    reset,
    goToPage,
  };
}

export function countFilters(...values: string[]): number {
  return values.filter(Boolean).length;
}

export function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Unknown error";
}
