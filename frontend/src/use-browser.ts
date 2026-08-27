import { useCallback, useEffect, useRef, useState } from "react";
import type { SetStateAction } from "react";

import type { ListQuery, ListResult } from "./api";
import {
  filterSearch,
  listQuery,
  listSearch,
  setExactFilter,
  setFilterSearch,
} from "./filters";
import type { BrowserQuery, FilterScalar } from "./filters";
import { NAVIGATION_EVENT } from "./routes";

const EMPTY_RESULT = { items: [], nextPageToken: "", totalSize: 0n };

export function useBrowser<Item>(
  defaultOrderBy: string,
  loadPage: (query: ListQuery, signal: AbortSignal) => Promise<ListResult<Item>>,
) {
  const [query, setQuery] = useState(() => listQuery(window.location.search, defaultOrderBy));
  const [search, setSearch] = useState(() => filterSearch(query.filter));
  const [result, setResult] = useState<ListResult<Item>>(EMPTY_RESULT);
  const [loadedQuery, setLoadedQuery] = useState<BrowserQuery | null>(null);
  const [previousTokens, setPreviousTokens] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const restoring = useRef(false);
  const queryRef = useRef(query);

  useEffect(() => { queryRef.current = query; }, [query]);

  useEffect(() => {
    const restore = () => {
      const next = listQuery(window.location.search, defaultOrderBy);
      if (sameQuery(next, queryRef.current)) return;
      restoring.current = true;
      setQuery(next);
      setSearch(filterSearch(next.filter));
      setPreviousTokens([]);
    };
    window.addEventListener("popstate", restore);
    window.addEventListener(NAVIGATION_EVENT, restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener(NAVIGATION_EVENT, restore);
    };
  }, [defaultOrderBy]);

  useEffect(() => {
    if (restoring.current) {
      restoring.current = false;
      return;
    }
    const next = `${window.location.pathname}${listSearch(query, defaultOrderBy)}`;
    window.history.replaceState(null, "", next);
  }, [defaultOrderBy, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery((current) => applySearch(current, search, defaultOrderBy));
      setPreviousTokens([]);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [defaultOrderBy, search]);

  useEffect(() => {
    const controller = new AbortController();
    loadPage(query, controller.signal)
      .then((next) => {
        setResult(next);
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

  const updateQuery = useCallback((update: SetStateAction<BrowserQuery>) => {
    setQuery(update);
    setPreviousTokens([]);
  }, []);

  const updateFilter = useCallback((field: string, value: FilterScalar) => {
    updateQuery((current) => ({
      ...current,
      filter: setExactFilter(current.filter, field, value),
      pageToken: "",
    }));
  }, [updateQuery]);

  const sortBy = useCallback((field: string) => {
    updateQuery((current) => ({
      ...current,
      orderBy: `${field} ${current.orderBy === `${field} desc` ? "asc" : "desc"}`,
      pageToken: "",
    }));
  }, [updateQuery]);

  const reset = useCallback(() => {
    setSearch("");
    updateQuery((current) => ({
      filter: "",
      orderBy: defaultOrderBy,
      pageSize: current.pageSize,
      pageToken: "",
    }));
  }, [defaultOrderBy, updateQuery]);

  const previousPage = useCallback(() => {
    const previous = previousTokens.at(-1);
    if (previous == null) return;
    setPreviousTokens((current) => current.slice(0, -1));
    setQuery((current) => ({ ...current, pageToken: previous }));
  }, [previousTokens]);

  const nextPage = useCallback(() => {
    if (result.nextPageToken === "") return;
    setPreviousTokens((current) => [...current, query.pageToken]);
    setQuery((current) => ({ ...current, pageToken: result.nextPageToken }));
  }, [query.pageToken, result.nextPageToken]);

  return {
    query,
    search,
    setSearch,
    result,
    loading: loadedQuery !== query,
    error,
    updateFilter,
    sortBy,
    sortByRelevance: () => updateQuery((current) => ({ ...current, orderBy: "", pageToken: "" })),
    setOrderBy: (orderBy: string) => updateQuery((current) => ({ ...current, orderBy, pageToken: "" })),
    reset,
    setPageSize: (pageSize: number) => updateQuery((current) => ({ ...current, pageSize, pageToken: "" })),
    nextPage,
    previousPage,
    hasPreviousPage: previousTokens.length > 0,
  };
}

function sameQuery(left: BrowserQuery, right: BrowserQuery): boolean {
  return left.filter === right.filter
    && left.orderBy === right.orderBy
    && left.pageSize === right.pageSize
    && left.pageToken === right.pageToken;
}

function applySearch(current: BrowserQuery, search: string, defaultOrderBy: string): BrowserQuery {
  const filter = setFilterSearch(current.filter, search);
  if (filter === current.filter) return current;
  const previousSearch = filterSearch(current.filter);
  let orderBy = current.orderBy;
  if (search === "" && orderBy === "") orderBy = defaultOrderBy;
  else if (previousSearch === "" && orderBy === defaultOrderBy) orderBy = "";
  return { ...current, filter, orderBy, pageToken: "" };
}

export function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Unknown error";
}
