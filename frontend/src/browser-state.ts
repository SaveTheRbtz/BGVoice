import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { INSTALLATION_NAME } from "./api";
import type { ListQuery, ListResult } from "./api";

export const PAGE_SIZES = [10, 25, 50, 100] as const;

export interface BrowserQuery {
  filter: string;
  orderBy: string;
  pageSize: number;
  pageToken: string;
}

export type AppRoute =
  | { name: "voices"; voiceId: string | null }
  | { name: "characters"; resourceName: string | null }
  | { name: "dialogues"; resourceName: string | null }
  | { name: "dialogue-lines" }
  | { name: "dialogue-transitions" }
  | { name: "character-sounds" }
  | { name: "races" }
  | { name: "character-classes" }
  | { name: "kits" }
  | { name: "identifier-definitions" }
  | { name: "pipeline" }
  | { name: "not-found" };

const NAVIGATION_EVENT = "bgvoice:navigate";
const DEFAULT_PAGE_SIZE = 25;

export function routeFromPath(pathname: string = window.location.pathname): AppRoute {
  const segments = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const [collection, resource, ...rest] = segments;
  if (collection == null) return { name: "voices", voiceId: null };
  if (collection === "voices" && rest.length === 0) {
    return {
      name: "voices",
      voiceId: resource == null ? null : canonicalName("voices", resource),
    };
  }
  if (collection === "characters" && rest.length === 0) {
    return {
      name: "characters",
      resourceName: resource == null ? null : canonicalName("characters", resource),
    };
  }
  if (collection === "dialogues" && rest.length === 0) {
    return {
      name: "dialogues",
      resourceName: resource == null ? null : canonicalName("dialogues", resource),
    };
  }
  if (segments.length === 1) {
    switch (collection) {
      case "dialogue-lines": return { name: "dialogue-lines" };
      case "dialogue-transitions": return { name: "dialogue-transitions" };
      case "character-sounds": return { name: "character-sounds" };
      case "pipeline": return { name: "pipeline" };
      default: return { name: "not-found" };
    }
  }
  if (collection === "definitions" && segments.length === 2) {
    switch (resource) {
      case "races": return { name: "races" };
      case "character-classes": return { name: "character-classes" };
      case "kits": return { name: "kits" };
      case "identifier-definitions": return { name: "identifier-definitions" };
      default: return { name: "not-found" };
    }
  }
  return { name: "not-found" };
}

export function voicePath(id?: string, search = ""): string {
  const path = id == null ? "/voices" : `/voices/${encodeURIComponent(resourceId(id))}`;
  return `${path}${search}`;
}

export function characterPath(resourceName?: string): string {
  return resourceName == null
    ? "/characters"
    : `/characters/${encodeURIComponent(resourceId(resourceName))}`;
}

export function resourceId(resourceName: string): string {
  return resourceName.slice(resourceName.lastIndexOf("/") + 1);
}

export function dialoguePath(resourceName?: string): string {
  return resourceName == null
    ? "/dialogues"
    : `/dialogues/${encodeURIComponent(resourceId(resourceName))}`;
}

function canonicalName(collection: "voices" | "characters" | "dialogues", id: string): string {
  return `${INSTALLATION_NAME}/${collection}/${id}`;
}

export function navigate(href: string, replace = false): void {
  const current = `${window.location.pathname}${window.location.search}`;
  if (current === href) return;
  window.history[replace ? "replaceState" : "pushState"](null, "", href);
  window.dispatchEvent(new Event(NAVIGATION_EVENT));
}

export function followLink(event: MouseEvent<HTMLAnchorElement>, href: string): void {
  if (
    event.button !== 0
    || event.metaKey
    || event.ctrlKey
    || event.shiftKey
    || event.altKey
  ) return;
  event.preventDefault();
  navigate(href);
}

export function useRoute(): AppRoute {
  const [route, setRoute] = useState(() => routeFromPath());
  useEffect(() => {
    const restore = () => setRoute(routeFromPath());
    window.addEventListener("popstate", restore);
    window.addEventListener(NAVIGATION_EVENT, restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener(NAVIGATION_EVENT, restore);
    };
  }, []);
  return route;
}

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
  if (query.filter !== "") parameters.set("filter", query.filter);
  if (query.orderBy !== "" && query.orderBy !== defaultOrderBy) {
    parameters.set("order_by", query.orderBy);
  }
  if (query.pageSize !== DEFAULT_PAGE_SIZE) {
    parameters.set("page_size", String(query.pageSize));
  }
  if (query.pageToken !== "") parameters.set("page_token", query.pageToken);
  const serialized = parameters.toString();
  return serialized === "" ? "" : `?${serialized}`;
}

type FilterScalar = string | number | boolean;

interface FilterParts {
  search: string;
  exact: Map<string, FilterScalar>;
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

export function setExactFilter(
  filter: string,
  field: string,
  value: FilterScalar,
): string {
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
  for (const clause of filter.split(" AND ").filter(Boolean)) {
    if (clause.startsWith("search(") && clause.endsWith(")")) {
      const serialized = clause.slice(7, -1);
      try {
        const parsed: unknown = JSON.parse(serialized);
        if (typeof parsed === "string") parts.search = parsed;
      } catch {
        // The API will report malformed URL filters.
      }
      continue;
    }
    const separator = clause.indexOf(" = ");
    if (separator < 1) continue;
    const field = clause.slice(0, separator);
    const serialized = clause.slice(separator + 3);
    if (serialized === "true" || serialized === "false") {
      parts.exact.set(field, serialized === "true");
      continue;
    }
    const numeric = Number(serialized);
    if (serialized !== "" && Number.isFinite(numeric)) {
      parts.exact.set(field, numeric);
      continue;
    }
    try {
      const parsed: unknown = JSON.parse(serialized);
      if (typeof parsed === "string") parts.exact.set(field, parsed);
    } catch {
      // The API will report malformed URL filters.
    }
  }
  return parts;
}

function serializeFilter(parts: FilterParts): string {
  const clauses: string[] = [];
  if (parts.search !== "") clauses.push(`search(${JSON.stringify(parts.search)})`);
  for (const [field, value] of parts.exact) {
    clauses.push(`${field} = ${typeof value === "string" ? JSON.stringify(value) : value}`);
  }
  return clauses.join(" AND ");
}

export function useBrowser<Item>(
  defaultOrderBy: string,
  loadPage: (query: ListQuery, signal: AbortSignal) => Promise<ListResult<Item>>,
) {
  const [query, setQuery] = useState(() => listQuery(window.location.search, defaultOrderBy));
  const [search, setSearch] = useState(() => filterSearch(query.filter));
  const [result, setResult] = useState<ListResult<Item>>({
    items: [],
    nextPageToken: "",
    totalSize: 0n,
  });
  const [loadedQuery, setLoadedQuery] = useState<BrowserQuery | null>(null);
  const [previousTokens, setPreviousTokens] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const restoring = useRef(false);
  const queryRef = useRef(query);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  useEffect(() => {
    const restore = () => {
      const next = listQuery(window.location.search, defaultOrderBy);
      const current = queryRef.current;
      if (
        next.filter === current.filter
        && next.orderBy === current.orderBy
        && next.pageSize === current.pageSize
        && next.pageToken === current.pageToken
      ) return;
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
      setQuery((current) => {
        const filter = setFilterSearch(current.filter, search);
        if (filter === current.filter) return current;
        const previousSearch = filterSearch(current.filter);
        const orderBy = search === "" && current.orderBy === ""
          ? defaultOrderBy
          : previousSearch === "" && current.orderBy === defaultOrderBy
            ? ""
            : current.orderBy;
        return { ...current, filter, orderBy, pageToken: "" };
      });
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

  const updateFilter = useCallback((field: string, value: FilterScalar) => {
    setQuery((current) => ({
      ...current,
      filter: setExactFilter(current.filter, field, value),
      pageToken: "",
    }));
    setPreviousTokens([]);
  }, []);

  const sortBy = useCallback((field: string) => {
    setQuery((current) => {
      const [activeField, activeDirection] = current.orderBy.split(" ");
      const direction = activeField === field && activeDirection === "desc" ? "asc" : "desc";
      return { ...current, orderBy: `${field} ${direction}`, pageToken: "" };
    });
    setPreviousTokens([]);
  }, []);

  const sortByRelevance = useCallback(() => {
    setQuery((current) => ({ ...current, orderBy: "", pageToken: "" }));
    setPreviousTokens([]);
  }, []);

  const setOrderBy = useCallback((orderBy: string) => {
    setQuery((current) => ({ ...current, orderBy, pageToken: "" }));
    setPreviousTokens([]);
  }, []);

  const reset = useCallback(() => {
    setSearch("");
    setQuery((current) => ({
      filter: "",
      orderBy: defaultOrderBy,
      pageSize: current.pageSize,
      pageToken: "",
    }));
    setPreviousTokens([]);
  }, [defaultOrderBy]);

  const setPageSize = useCallback((pageSize: number) => {
    setQuery((current) => ({ ...current, pageSize, pageToken: "" }));
    setPreviousTokens([]);
  }, []);

  const nextPage = useCallback(() => {
    if (result.nextPageToken === "") return;
    setPreviousTokens((current) => [...current, query.pageToken]);
    setQuery((current) => ({ ...current, pageToken: result.nextPageToken }));
  }, [query.pageToken, result.nextPageToken]);

  const previousPage = useCallback(() => {
    const previous = previousTokens.at(-1);
    if (previous == null) return;
    setPreviousTokens((current) => current.slice(0, -1));
    setQuery((current) => ({ ...current, pageToken: previous }));
  }, [previousTokens]);

  return {
    query,
    search,
    setSearch,
    result,
    loading: loadedQuery !== query,
    error,
    updateFilter,
    sortBy,
    sortByRelevance,
    setOrderBy,
    reset,
    setPageSize,
    nextPage,
    previousPage,
    hasPreviousPage: previousTokens.length > 0,
  };
}

export function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Unknown error";
}
