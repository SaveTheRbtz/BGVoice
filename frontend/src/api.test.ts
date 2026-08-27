import { describe, expect, it } from "vitest";

import { withQuery } from "./api";
import type {
  ClassQuery,
  IdentifierQuery,
  TransitionQuery,
  VoiceQuery,
} from "./types";

describe("metadata API queries", () => {
  it("sends active class filters and omits empty search and sort fields", () => {
    const query: ClassQuery = {
      page: 2,
      page_size: 50,
      q: "",
      sort: "",
      direction: "asc",
      campaign: "BG1",
      fallen: "false",
      class_id: "12",
    };

    const url = new URL(withQuery("/api/classes", query), "http://bgvoice.test");

    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "2",
      page_size: "50",
      direction: "asc",
      campaign: "BG1",
      fallen: "false",
      class_id: "12",
    });
  });

  it("preserves typed identifier search and ordering fields", () => {
    const query: IdentifierQuery = {
      page: 1,
      page_size: 25,
      q: "dragon",
      sort: "value",
      direction: "desc",
      kind: "animation",
    };

    const url = new URL(withQuery("/api/identifiers", query), "http://bgvoice.test");

    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "1",
      page_size: "25",
      q: "dragon",
      sort: "value",
      direction: "desc",
      kind: "animation",
    });
  });

  it("serializes grouped-voice filtering without overriding relevance", () => {
    const query: VoiceQuery = {
      page: 1,
      page_size: 25,
      q: "aerie",
      sort: "",
      direction: "desc",
      voice_id: "aerie-companion",
      has_dialogue: "true",
    };

    const url = new URL(withQuery("/api/voices", query), "http://bgvoice.test");

    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "1",
      page_size: "25",
      q: "aerie",
      direction: "desc",
      voice_id: "aerie-companion",
      has_dialogue: "true",
    });
  });

  it("serializes transition termination and explicit sort fields", () => {
    const query: TransitionQuery = {
      page: 3,
      page_size: 10,
      q: "Global",
      sort: "location",
      direction: "asc",
      terminates_dialog: "false",
    };

    const url = new URL(withQuery("/api/transitions", query), "http://bgvoice.test");

    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "3",
      page_size: "10",
      q: "Global",
      sort: "location",
      direction: "asc",
      terminates_dialog: "false",
    });
  });
});
