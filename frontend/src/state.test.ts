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
  it("maps every route shape and writes canonical resource paths", () => {
    const routes = [
      ["/", { name: "voices", voiceName: null }],
      ["/voices", { name: "voices", voiceName: null }],
      ["/voices/imoen", { name: "voices", voiceName: `${ROOT}/voices/imoen` }],
      ["/characters/aerie-cre-10f6d857", { name: "characters", resourceName: AERIE }],
      ["/dialogues/imoen2j-dlg-789f493a", { name: "dialogues", resourceName: IMOEN_DIALOGUE }],
      ["/dialogue-lines", { name: "dialogue-lines", lineKind: "npc" }],
      ["/dialogue-lines/npc", { name: "dialogue-lines", lineKind: "npc" }],
      ["/dialogue-lines/player", { name: "dialogue-lines", lineKind: "player" }],
      ["/dialogue-lines/journal", { name: "dialogue-lines", lineKind: "journal" }],
      ["/readable-items", { name: "readable-items" }],
      ["/dialogue-lines/unknown", { name: "not-found" }],
      ["/pipeline", { name: "pipeline" }],
      ["/extraction-runs", { name: "extraction-runs" }],
      ["/pipeline/unknown", { name: "not-found" }],
      ["/definitions/races", { name: "races" }],
      ["/definitions/character-classes", { name: "character-classes" }],
      ["/definitions/unknown", { name: "not-found" }],
      ["/voices/imoen/extra", { name: "not-found" }],
    ] satisfies ReadonlyArray<readonly [string, AppRoute]>;
    for (const [path, expected] of routes) expect(routeFromPath(path)).toEqual(expected);

    const paths = [
      [voicePath(`${ROOT}/voices/imoen`), "/voices/imoen"],
      [voicePath(`${ROOT}/voices/imoen`, "?page_size=50"), "/voices/imoen?page_size=50"],
      [characterPath(AERIE), "/characters/aerie-cre-10f6d857"],
      [dialoguePath(IMOEN_DIALOGUE), "/dialogues/imoen2j-dlg-789f493a"],
      [dialoguePath(IMOEN_DIALOGUE, "?page_size=50"), "/dialogues/imoen2j-dlg-789f493a?page_size=50"],
    ] as const;
    for (const [actual, expected] of paths) expect(actual).toBe(expected);

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
