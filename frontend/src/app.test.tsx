// @vitest-environment jsdom

import { create } from "@bufbuild/protobuf";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ListQuery, ListResult } from "./api";
import {
  type Character,
  CharacterSchema,
  type DialogueLine,
  DialogueLineSchema,
  type ExtractionRun,
  type Installation,
  InstallationSchema,
  type Voice,
  VoiceSchema,
} from "./gen/bgvoice/v1/pipeline_pb";

const api = vi.hoisted(() => ({
  getInstallation: vi.fn<(signal?: AbortSignal) => Promise<Installation>>(),
  getVoice: vi.fn<(name: string, signal?: AbortSignal) => Promise<Voice>>(),
  getCharacter: vi.fn<(name: string, signal?: AbortSignal) => Promise<Character>>(),
  listVoices: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Voice>>
  >(),
  listDialogueLines: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<DialogueLine>>
  >(),
  listExtractionRuns: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<ExtractionRun>>
  >(),
}));

vi.mock(import("./api"), async (importOriginal) => ({
  ...(await importOriginal()),
  getInstallation: api.getInstallation,
  getVoice: api.getVoice,
  getCharacter: api.getCharacter,
  listVoices: api.listVoices,
  listDialogueLines: api.listDialogueLines,
  listExtractionRuns: api.listExtractionRuns,
}));

import App from "./App";

const installation = create(InstallationSchema, {
  name: "installations/bg2ee-eet",
  summary: {
    npcLines: 11n,
    playerLines: 7n,
    journalLines: 2n,
    generatedVoices: 7n,
    uniqueInworldVoices: 3n,
    voiceCreationFailures: 1n,
    dialogueDirectionFailures: 3n,
    audioGenerationFailures: 6n,
  },
});

const voice = create(VoiceSchema, {
  name: "installations/bg2ee-eet/voices/imoen",
  voiceId: "imoen",
  displayName: "Imoen",
  prompt: "Warm, quick-witted and mischievous. Keep an easy Amnian cadence.",
  characters: [
    { name: "installations/bg2ee-eet/characters/imoen15-cre-fe85cc5b", engineResourceName: "IMOEN15.CRE", npcLineCount: 812n },
    { name: "installations/bg2ee-eet/characters/imoen-cre-3768424f", engineResourceName: "IMOEN.CRE", npcLineCount: 6108n },
  ],
  dialogues: [
    { name: "installations/bg2ee-eet/dialogues/imoenb-dlg-e9a04d8e", engineResourceName: "IMOENB.DLG", npcLineCount: 12n },
    { name: "installations/bg2ee-eet/dialogues/imoen2j-dlg-789f493a", engineResourceName: "IMOEN2J.DLG", npcLineCount: 5758n },
  ],
  npcLineCount: 6108n,
  directedLineCount: 100n,
  generatedAudioCount: 92n,
  generatedVoice: {
    description: "Youthful, warm and quick-witted, with a mischievous Amnian lilt.",
    languageCode: "en-GB",
    inworldVoiceId: "voice-imoen",
  },
});

const character = create(CharacterSchema, {
  name: "installations/bg2ee-eet/characters/imoen-cre-3768424f",
  engineResourceName: "IMOEN.CRE",
  resref: "IMOEN",
  displayName: "Imoen",
  voice: voice.name,
});

const line = create(DialogueLineSchema, {
  name: "installations/bg2ee-eet/dialogueLines/imoen2j-dlg-0-0-ecdf1e0b",
  dialogue: "installations/bg2ee-eet/dialogues/imoen2j-dlg-789f493a",
  text: "Heya! It's me, Imoen!",
  tokens: ["PLAYER2", "CHARNAME", "DAY", "PLAYER1", "CHARNAME", "PLAYER2", "CHARNAME", "PLAYER1"],
  stateTriggerIndex: 23,
  directions: [{
    id: "direction-imoen-line-1",
    voice: voice.name,
    voiceDisplayName: "Imoen",
    result: {
      case: "character",
      value: { directedDialogue: "[brightly] Heya! It's me, Imoen!" },
    },
    audioUrl: "/v1/installations/bg2ee-eet/generatedAudio/audio-1:download",
  }, {
    id: "direction-imoen-line-2",
    voice: voice.name,
    voiceDisplayName: "Imoen",
    result: {
      case: "narrator",
      value: { directedDialogue: "[narrate gently] The chamber falls silent." },
    },
    audioUrl: "/v1/installations/bg2ee-eet/generatedAudio/audio-2:download",
  }],
});

beforeEach(() => {
  vi.resetAllMocks();
  api.getInstallation.mockResolvedValue(installation);
  api.listVoices.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 1n });
  api.getVoice.mockResolvedValue(voice);
  api.getCharacter.mockResolvedValue(character);
  api.listDialogueLines.mockResolvedValue({ items: [line], nextPageToken: "", totalSize: 1n });
  api.listExtractionRuns.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("application jobs", () => {
  it("reviews a voice and follows its highest-workload character", async () => {
    window.history.replaceState(null, "", "/voices/imoen");
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Imoen", level: 2 })).toBeTruthy();
    expect(api.getVoice).toHaveBeenCalledWith(voice.name, expect.any(AbortSignal));
    expect(screen.getByText(voice.prompt)).toBeTruthy();
    expect(screen.getByText(voice.generatedVoice?.description ?? "")).toBeTruthy();
    expect(screen.getByText("voice-imoen")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Needs audio" }).getAttribute("href"))
      .toContain("voice_id");
    expect(screen.getAllByRole("link", { name: /^IMOEN(?:15)? ×/ }).map((link) => link.textContent))
      .toEqual(["IMOEN × 6,108", "IMOEN15 × 812"]);
    expect(screen.getAllByRole("link", { name: /^IMOEN(?:2J|B) ×/ }).map((link) => link.textContent))
      .toEqual(["IMOEN2J × 5,758", "IMOENB × 12"]);

    await user.click(screen.getByRole("link", { name: "IMOEN × 6,108" }));
    await waitFor(() => expect(window.location.pathname).toBe("/characters/imoen-cre-3768424f"));
    expect(await screen.findByRole("heading", { name: "Imoen", level: 1 })).toBeTruthy();
    expect(api.getCharacter).toHaveBeenCalledWith(character.name, expect.any(AbortSignal));
  });

  it("filters dialogue lines by canonical voice identity", async () => {
    const armoredFigure = create(VoiceSchema, {
      name: "installations/bg2ee-eet/voices/armored-figure-befd8070",
      voiceId: "armored figure",
      displayName: "Armored Figure",
      prompt: "A guarded voice resonating from inside a heavy helm.",
    });
    api.getVoice.mockResolvedValue(armoredFigure);
    window.history.replaceState(
      null,
      "",
      "/voices/armored-figure-befd8070?filter=search(%22armored+figure%22)",
    );
    render(<App />);

    const href = (await screen.findByRole("link", { name: "All source lines" })).getAttribute("href");
    const url = new URL(href ?? "", window.location.origin);
    expect(url.pathname).toBe("/dialogue-lines");
    expect(url.searchParams.get("filter")).toBe(
      'voice_id = "armored figure" AND line_kind = "npc"',
    );
  });

  it("browses dialogue text with condensed, ordered context", async () => {
    window.history.replaceState(null, "", "/dialogue-lines");
    const user = userEvent.setup();
    render(<App />);

    const text = await screen.findByRole("button", { name: line.text });
    expect(text.getAttribute("aria-expanded")).toBe("false");
    await user.click(text);
    expect(text.getAttribute("aria-expanded")).toBe("true");

    const context = screen.getAllByRole("cell")
      .find((cell) => cell.textContent?.startsWith("CHARNAME×3"));
    expect(context?.textContent).toBe(
      "CHARNAME×3PLAYER1×2PLAYER2×2DAYState trigger 23 · unresolved",
    );
    expect(screen.getByText("[brightly] Heya! It's me, Imoen!")).toBeTruthy();
    expect(screen.getByText("[narrate gently] The chamber falls silent.")).toBeTruthy();
    const audio = screen.getByLabelText("Audio sample for Imoen");
    expect(audio.getAttribute("preload")).toBe("none");
    expect(audio.getAttribute("src")).toBe(line.directions[0]?.audioUrl);
    expect(screen.getByLabelText("Narrator audio sample attributed to Imoen")).toBeTruthy();
    expect(api.listDialogueLines).toHaveBeenCalledWith(
      expect.objectContaining({ filter: "", orderBy: "", pageSize: 25 }),
      expect.any(AbortSignal),
    );
  });

  it("summarizes dialogue kinds and unresolved generation failures", async () => {
    window.history.replaceState(null, "", "/pipeline");
    render(<App />);

    for (const [label, value] of [
      ["NPC lines", "11"],
      ["Player lines", "7"],
      ["Journal lines", "2"],
    ] as const) {
      const stat = (await screen.findByText(label)).closest("article");
      expect(stat).not.toBeNull();
      expect(within(stat!).getByText(value)).toBeTruthy();
    }
    expect(screen.queryByText("Dialogue lines")).toBeNull();

    const progress = within(await screen.findByRole("region", { name: "Voice-over progress" }));
    const assignments = progress.getByText("Voice assignments").closest("article");
    const providerVoices = progress.getByText("Unique Inworld voices").closest("article");
    expect(assignments).not.toBeNull();
    expect(providerVoices).not.toBeNull();
    expect(within(assignments!).getByText("7")).toBeTruthy();
    expect(within(providerVoices!).getByText("3")).toBeTruthy();

    const failures = within(screen.getByRole("group", { name: "Generation failures" }));
    expect(failures.getByText("Voice creation")).toBeTruthy();
    expect(failures.getByText("1")).toBeTruthy();
    expect(failures.getByText("Dialogue direction")).toBeTruthy();
    expect(failures.getByText("3")).toBeTruthy();
    expect(failures.getByText("Audio generation")).toBeTruthy();
    expect(failures.getByText("6")).toBeTruthy();
  });
});
