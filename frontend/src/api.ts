import type {
  CharacterDetailResponse,
  CharacterPage,
  CharacterQuery,
  ClassPage,
  ClassQuery,
  DialogueLinePage,
  DialoguePage,
  DialogueQuery,
  FilterOptions,
  IdentifierPage,
  IdentifierQuery,
  KitPage,
  KitQuery,
  LineQuery,
  PipelineStats,
  RacePage,
  RaceQuery,
  TransitionPage,
  TransitionQuery,
  VoicePage,
  VoiceQuery,
} from "./types";

type ApiQuery =
  | CharacterQuery
  | DialogueQuery
  | LineQuery
  | RaceQuery
  | ClassQuery
  | KitQuery
  | IdentifierQuery
  | VoiceQuery
  | TransitionQuery;

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

export function withQuery(path: string, query: ApiQuery): string {
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

export function getRaces(query: RaceQuery, signal?: AbortSignal): Promise<RacePage> {
  return fetchJson<RacePage>(withQuery("/api/races", query), signal);
}

export function getClasses(query: ClassQuery, signal?: AbortSignal): Promise<ClassPage> {
  return fetchJson<ClassPage>(withQuery("/api/classes", query), signal);
}

export function getKits(query: KitQuery, signal?: AbortSignal): Promise<KitPage> {
  return fetchJson<KitPage>(withQuery("/api/kits", query), signal);
}

export function getIdentifiers(
  query: IdentifierQuery,
  signal?: AbortSignal,
): Promise<IdentifierPage> {
  return fetchJson<IdentifierPage>(withQuery("/api/identifiers", query), signal);
}

export function getVoices(query: VoiceQuery, signal?: AbortSignal): Promise<VoicePage> {
  return fetchJson<VoicePage>(withQuery("/api/voices", query), signal);
}

export function getTransitions(
  query: TransitionQuery,
  signal?: AbortSignal,
): Promise<TransitionPage> {
  return fetchJson<TransitionPage>(withQuery("/api/transitions", query), signal);
}
