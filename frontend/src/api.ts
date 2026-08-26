import type {
  CharacterDetailResponse,
  CharacterPage,
  CharacterQuery,
  DialogueLinePage,
  DialoguePage,
  DialogueQuery,
  FilterOptions,
  LineQuery,
  PipelineStats,
} from "./types";

type ApiQuery = CharacterQuery | DialogueQuery | LineQuery;

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    const status = `${response.status} ${response.statusText}`.trim();
    const body = (await response.text()).trim();
    throw new Error(body ? `${status}: ${body}` : status);
  }
  return (await response.json()) as T;
}

function withQuery(path: string, query: ApiQuery): string {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== "") parameters.set(key, String(value));
  }
  const serialized = parameters.toString();
  return serialized ? `${path}?${serialized}` : path;
}

export function getStats(signal?: AbortSignal): Promise<PipelineStats> {
  return fetchJson<PipelineStats>("/api/stats", signal);
}

export function getFilterOptions(signal?: AbortSignal): Promise<FilterOptions> {
  return fetchJson<FilterOptions>("/api/filter-options", signal);
}

export function getCharacters(
  query: CharacterQuery,
  signal?: AbortSignal,
): Promise<CharacterPage> {
  return fetchJson<CharacterPage>(withQuery("/api/characters", query), signal);
}

export function getCharacterDetail(
  resourceName: string,
  signal?: AbortSignal,
): Promise<CharacterDetailResponse> {
  return fetchJson<CharacterDetailResponse>(
    `/api/characters/${encodeURIComponent(resourceName)}`,
    signal,
  );
}

export function getDialogues(
  query: DialogueQuery,
  signal?: AbortSignal,
): Promise<DialoguePage> {
  return fetchJson<DialoguePage>(withQuery("/api/dialogues", query), signal);
}

export function getLines(query: LineQuery, signal?: AbortSignal): Promise<DialogueLinePage> {
  return fetchJson<DialogueLinePage>(withQuery("/api/lines", query), signal);
}
