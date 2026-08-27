import { describe, expect, it } from "vitest";

import { browserQuery, browserSearch, browserTab } from "./browser-state";
import type { CharacterQuery, VoiceQuery } from "./types";

const characterDefaults: CharacterQuery = {
  page: 1,
  page_size: 25,
  q: "",
  status: "",
  source_kind: "",
  has_dialog: "",
  gender_id: "",
  race_id: "",
  class_id: "",
  attribution_status: "",
  sort: "",
  direction: "desc",
};

const voiceDefaults: VoiceQuery = {
  page: 1,
  page_size: 25,
  q: "",
  voice_id: "",
  has_dialogue: "",
  sort: "",
  direction: "desc",
};

describe("browser URL state", () => {
  it("restores the active tab and its typed pagination and filter values", () => {
    const search = "?tab=voices&page=3&page_size=50&q=warm&voice_id=aerie&has_dialogue=true";

    expect(browserTab(search)).toBe("voices");
    expect(browserQuery(voiceDefaults, search)).toEqual({
      ...voiceDefaults,
      page: 3,
      page_size: 50,
      q: "warm",
      voice_id: "aerie",
      has_dialogue: "true",
    });
  });

  it("keeps old character query links useful and normalizes changed fields", () => {
    const restored = browserQuery(
      characterDefaults,
      "?page=2&attribution_status=matched&sort=dialogue_transition_count",
    );

    expect(browserTab("?page=2&attribution_status=matched")).toBe("characters");
    expect(browserSearch("characters", restored, characterDefaults)).toBe(
      "?tab=characters&page=2&attribution_status=matched&sort=dialogue_transition_count",
    );
  });

  it("ignores invalid numeric URL values", () => {
    expect(browserQuery(voiceDefaults, "?page=zero&page_size=-1")).toEqual(
      voiceDefaults,
    );
  });
});
