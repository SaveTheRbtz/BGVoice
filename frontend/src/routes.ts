import { useEffect, useState } from "react";
import type { MouseEvent } from "react";

import { INSTALLATION_NAME } from "./api";
import { setExactFilter } from "./filters";

export type AppRoute =
  | { name: "voices"; voiceName: string | null }
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

export const NAVIGATION_EVENT = "bgvoice:navigate";

const NOT_FOUND = { name: "not-found" } as const;

const COLLECTION_ROUTES = {
  voices: (id?: string): AppRoute => ({
    name: "voices",
    voiceName: id == null ? null : canonicalName("voices", id),
  }),
  characters: (id?: string): AppRoute => ({
    name: "characters",
    resourceName: id == null ? null : canonicalName("characters", id),
  }),
  dialogues: (id?: string): AppRoute => ({
    name: "dialogues",
    resourceName: id == null ? null : canonicalName("dialogues", id),
  }),
} satisfies Record<string, (id?: string) => AppRoute>;

const SINGLE_ROUTES = {
  "dialogue-lines": { name: "dialogue-lines" },
  "dialogue-transitions": { name: "dialogue-transitions" },
  "character-sounds": { name: "character-sounds" },
  pipeline: { name: "pipeline" },
} satisfies Record<string, AppRoute>;

const DEFINITION_ROUTES = {
  races: { name: "races" },
  "character-classes": { name: "character-classes" },
  kits: { name: "kits" },
  "identifier-definitions": { name: "identifier-definitions" },
} satisfies Record<string, AppRoute>;

export function routeFromPath(pathname: string = window.location.pathname): AppRoute {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return COLLECTION_ROUTES.voices();

  const [collection, resource] = segments;
  const collectionRoute = COLLECTION_ROUTES[collection as keyof typeof COLLECTION_ROUTES];
  if (collectionRoute != null && segments.length <= 2) return collectionRoute(resource);
  if (segments.length === 1) return SINGLE_ROUTES[collection as keyof typeof SINGLE_ROUTES] ?? NOT_FOUND;
  if (collection === "definitions" && segments.length === 2) {
    return DEFINITION_ROUTES[resource as keyof typeof DEFINITION_ROUTES] ?? NOT_FOUND;
  }
  return NOT_FOUND;
}

export function voicePath(id?: string, search = ""): string {
  return `${resourcePath("voices", id)}${search}`;
}

export function characterPath(resourceName?: string): string {
  return resourcePath("characters", resourceName);
}

export function dialoguePath(resourceName?: string): string {
  return resourcePath("dialogues", resourceName);
}

export function dialogueLinesPath(
  filters: Readonly<Record<string, string | boolean>> = {},
): string {
  let filter = "";
  for (const [field, value] of Object.entries(filters)) {
    filter = setExactFilter(filter, field, value);
  }
  const parameters = new URLSearchParams();
  if (filter !== "") parameters.set("filter", filter);
  const search = parameters.toString();
  return search === "" ? "/dialogue-lines" : `/dialogue-lines?${search}`;
}

export function resourceId(resourceName: string): string {
  return resourceName.slice(resourceName.lastIndexOf("/") + 1);
}

function resourcePath(collection: string, name?: string): string {
  return name == null
    ? `/${collection}`
    : `/${collection}/${resourceId(name)}`;
}

function canonicalName(collection: keyof typeof COLLECTION_ROUTES, id: string): string {
  return `${INSTALLATION_NAME}/${collection}/${id}`;
}

export function navigate(href: string, replace = false): void {
  const current = `${window.location.pathname}${window.location.search}`;
  if (current === href) return;
  window.history[replace ? "replaceState" : "pushState"](null, "", href);
  window.dispatchEvent(new Event(NAVIGATION_EVENT));
}

export function followLink(event: MouseEvent<HTMLAnchorElement>, href: string): void {
  const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  if (event.button !== 0 || modified) return;
  event.preventDefault();
  navigate(href);
}

export function useRoute(): AppRoute {
  const [route, setRoute] = useState(routeFromPath);
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
