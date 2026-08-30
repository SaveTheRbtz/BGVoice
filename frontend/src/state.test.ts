import { describe, expect, it } from "vitest";

import {
  countFilters, filterSearch, filterValue, listQuery, listSearch,
  setExactFilter, setFilterSearch,
} from "./filters";
import {
  characterPath,
  characterSoundsPath,
  dialogueLinesPath,
  dialoguePath,
  dialogueTransitionsPath,
  routeFromPath,
  voicePath,
} from "./routes";
import type { AppRoute } from "./routes";

const ROOT = "installations/bg2ee-eet";
const AERIE = `${ROOT}/characters/aerie-cre-10f6d857`;
const IMOEN_DIALOGUE = `${ROOT}/dialogues/imoen2j-dlg-789f493a`;

describe("public URL state", () => {
  it.for([
    { path: "/", expected: { name: "voices", voiceName: null } },
    { path: "/voices", expected: { name: "voices", voiceName: null } },
    { path: "/voices/imoen", expected: { name: "voices", voiceName: `${ROOT}/voices/imoen` } },
    { path: "/characters/aerie-cre-10f6d857", expected: { name: "characters", resourceName: AERIE } },
    { path: "/dialogues/imoen2j-dlg-789f493a", expected: { name: "dialogues", resourceName: IMOEN_DIALOGUE } },
    { path: "/dialogue-lines", expected: { name: "dialogue-lines", lineKind: "npc" } },
    { path: "/dialogue-lines/npc", expected: { name: "dialogue-lines", lineKind: "npc" } },
    { path: "/dialogue-lines/player", expected: { name: "dialogue-lines", lineKind: "player" } },
    { path: "/dialogue-lines/journal", expected: { name: "dialogue-lines", lineKind: "journal" } },
    { path: "/readable-items", expected: { name: "readable-items" } },
    { path: "/pipeline", expected: { name: "pipeline" } },
    { path: "/extraction-runs", expected: { name: "extraction-runs" } },
    { path: "/definitions/races", expected: { name: "races" } },
    { path: "/definitions/character-classes", expected: { name: "character-classes" } },
    { path: "/dialogue-lines/unknown", expected: { name: "not-found" } },
    { path: "/pipeline/unknown", expected: { name: "not-found" } },
    { path: "/definitions/unknown", expected: { name: "not-found" } },
    { path: "/voices/imoen/extra", expected: { name: "not-found" } },
  ] satisfies ReadonlyArray<{ path: string; expected: AppRoute }>)("parses $path", ({ path, expected }) => {
    expect(routeFromPath(path)).toEqual(expected);
  });

  it.for([
    { actual: voicePath(`${ROOT}/voices/imoen`), expected: "/voices/imoen" },
    { actual: voicePath(`${ROOT}/voices/imoen`, "?page_size=50"), expected: "/voices/imoen?page_size=50" },
    { actual: characterPath(AERIE), expected: "/characters/aerie-cre-10f6d857" },
    { actual: dialoguePath(IMOEN_DIALOGUE), expected: "/dialogues/imoen2j-dlg-789f493a" },
    { actual: dialoguePath(IMOEN_DIALOGUE, "?page_size=50"), expected: "/dialogues/imoen2j-dlg-789f493a?page_size=50" },
  ])("writes $expected", ({ actual, expected }) => {
    expect(actual).toBe(expected);
  });

  it("builds typed cross-resource filters", () => {
    const lineUrl = new URL(
      dialogueLinesPath({ voice_id: "imoen", voiced: false }),
      "http://localhost",
    );
    expect(lineUrl.pathname).toBe("/dialogue-lines/npc");
    expect(lineUrl.searchParams.get("filter")).toBe('voice_id = "imoen" AND voiced = false');

    const journalUrl = new URL(dialogueLinesPath({ line_kind: "journal" }), "http://localhost");
    expect(journalUrl.pathname).toBe("/dialogue-lines/journal");
    expect(journalUrl.search).toBe("");

    const transitionUrl = new URL(dialogueTransitionsPath("IMOEN2J.DLG"), "http://localhost");
    expect(transitionUrl.searchParams.get("filter"))
      .toBe('dialogue_resource_name = "IMOEN2J.DLG"');

    const soundsUrl = new URL(characterSoundsPath("IMOEN.CRE"), "http://localhost");
    expect(soundsUrl.searchParams.get("filter")).toBe('character_resource_name = "IMOEN.CRE"');
  });

  it("round-trips shareable list state and lets full-text relevance override defaults", () => {
    const query = {
      filter: 'search("warm alto") AND source_kind = "override"',
      orderBy: "npc_line_count desc",
      pageSize: 50,
      pageToken: "AAAAAAAAADKqMMePzBTFkFT7_hv3j31j",
    };
    expect(listQuery(listSearch(query))).toEqual(query);
    expect(listSearch({ ...query, filter: "", pageSize: 25, pageToken: "" }, query.orderBy)).toBe("");
    expect(listQuery("", "npc_line_count desc"))
      .toMatchObject({ orderBy: "npc_line_count desc", pageSize: 25 });
    expect(listQuery('?filter=search%28%22imoen%22%29', "npc_line_count desc").orderBy).toBe("");
    expect(listQuery("?filter=search%28%22imoen%22%29&order_by=display_name+asc").orderBy)
      .toBe("display_name asc");
    expect(listQuery("?page_size=37").pageSize).toBe(25);
  });
});

it("composes, reads, and removes typed filter clauses", () => {
  let filter = setFilterSearch("", "  Imoen  ");
  for (const [field, value] of [
    ["source_kind", "override"],
    ["race_id", 1],
    ["attributed", true],
  ] as const) filter = setExactFilter(filter, field, value);
  expect(filter).toBe('search("Imoen") AND source_kind = "override" AND race_id = 1 AND attributed = true');
  expect([filterSearch(filter), filterValue(filter, "race_id"), countFilters(filter)])
    .toEqual(["Imoen", "1", 4]);
  expect(setExactFilter(filter, "source_kind", ""))
    .toBe('search("Imoen") AND race_id = 1 AND attributed = true');
});
