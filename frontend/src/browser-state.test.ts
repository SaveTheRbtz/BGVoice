import { describe, expect, it } from "vitest";

import {
  characterPath,
  countFilters,
  filterSearch,
  filterValue,
  listQuery,
  listSearch,
  dialoguePath,
  routeFromPath,
  setExactFilter,
  setFilterSearch,
  voicePath,
} from "./browser-state";

describe("resource routes", () => {
  it("uses voices as the root and restores canonical detail routes", () => {
    expect(routeFromPath("/")).toEqual({ name: "voices", voiceId: null });
    expect(routeFromPath("/voices")).toEqual({ name: "voices", voiceId: null });
    expect(routeFromPath("/voices/imoen")).toEqual({
      name: "voices",
      voiceId: "installations/bg2ee-eet/voices/imoen",
    });
    expect(routeFromPath("/characters/AERIE.CRE")).toEqual({
      name: "characters",
      resourceName: "installations/bg2ee-eet/characters/AERIE.CRE",
    });
    expect(
      routeFromPath("/dialogues/IMOEN2J.DLG"),
    ).toEqual({
      name: "dialogues",
      resourceName: "installations/bg2ee-eet/dialogues/IMOEN2J.DLG",
    });
  });

  it("groups definition resources under one stable path", () => {
    expect(routeFromPath("/definitions/races")).toEqual({ name: "races" });
    expect(routeFromPath("/definitions/character-classes")).toEqual({
      name: "character-classes",
    });
    expect(routeFromPath("/definitions/unknown")).toEqual({ name: "not-found" });
  });

  it("encodes canonical resource names into one route segment", () => {
    expect(voicePath("installations/bg2ee-eet/voices/imoen")).toBe("/voices/imoen");
    expect(voicePath("installations/bg2ee-eet/voices/imoen", "?page_size=50")).toBe("/voices/imoen?page_size=50");
    expect(characterPath("installations/bg2ee-eet/characters/AERIE.CRE")).toBe(
      "/characters/AERIE.CRE",
    );
    expect(dialoguePath("installations/bg2ee-eet/dialogues/IMOEN2J.DLG")).toBe(
      "/dialogues/IMOEN2J.DLG",
    );
  });
});

describe("list URL state", () => {
  it("round-trips the public filter, order, size, and opaque cursor fields", () => {
    const query = {
      filter: 'search("warm alto") AND source_kind = "override"',
      orderBy: "npc_line_count desc",
      pageSize: 50,
      pageToken: "eyJvZmZzZXQiOjUwfQ==",
    };
    const search = listSearch(query);

    expect(new URLSearchParams(search).get("order_by")).toBe("npc_line_count desc");
    expect(listQuery(search)).toEqual(query);
  });

  it("keeps defaults out of compact shareable URLs", () => {
    expect(listSearch({
      filter: "",
      orderBy: "npc_line_count desc",
      pageSize: 25,
      pageToken: "",
    }, "npc_line_count desc")).toBe("");
  });

  it("uses BM25 relevance when a search has no explicit order", () => {
    expect(
      listQuery('?filter=search%28%22imoen%22%29', "npc_line_count desc").orderBy,
    ).toBe("");
  });

  it("ignores unsupported page sizes", () => {
    expect(listQuery("?page_size=37").pageSize).toBe(25);
  });
});

describe("typed filter composition", () => {
  it("composes search, enum, number, and boolean clauses", () => {
    let filter = setFilterSearch("", "  Imoen  ");
    filter = setExactFilter(filter, "source_kind", "override");
    filter = setExactFilter(filter, "race_id", 1);
    filter = setExactFilter(filter, "attributed", true);

    expect(filter).toBe(
      'search("Imoen") AND source_kind = "override" AND race_id = 1 AND attributed = true',
    );
    expect(filterSearch(filter)).toBe("Imoen");
    expect(filterValue(filter, "race_id")).toBe("1");
    expect(countFilters(filter)).toBe(4);
  });

  it("removes only the selected exact clause", () => {
    const filter = setExactFilter(
      'search("Imoen") AND source_kind = "override"',
      "source_kind",
      "",
    );
    expect(filter).toBe('search("Imoen")');
  });
});
