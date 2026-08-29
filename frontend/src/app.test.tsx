// @vitest-environment jsdom

import { create } from "@bufbuild/protobuf";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ListQuery, ListResult } from "./api";
import {
  AttributionStatus,
  type Character,
  type CharacterClass,
  CharacterClassSchema,
  CharacterSchema,
  DetailStatus,
  type Dialogue,
  DialogueSchema,
  type DialogueLine,
  DialogueLineKind,
  DialogueLineSchema,
  type ExtractionRun,
  type IdentifierDefinition,
  IdentifierDefinitionSchema,
  IdentifierKind,
  type Installation,
  InstallationSchema,
  type Kit,
  KitSchema,
  type Race,
  RaceSchema,
  type Voice,
  VoiceSchema,
  SourceKind,
} from "./gen/bgvoice/v1/pipeline_pb";

const api = vi.hoisted(() => ({
  getInstallation: vi.fn<(signal?: AbortSignal) => Promise<Installation>>(),
  getVoice: vi.fn<(name: string, signal?: AbortSignal) => Promise<Voice>>(),
  getCharacter: vi.fn<(name: string, signal?: AbortSignal) => Promise<Character>>(),
  getDialogue: vi.fn<(name: string, signal?: AbortSignal) => Promise<Dialogue>>(),
  listCharacters: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Character>>
  >(),
  listVoices: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Voice>>
  >(),
  listDialogues: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Dialogue>>
  >(),
  listDialogueLines: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<DialogueLine>>
  >(),
  listExtractionRuns: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<ExtractionRun>>
  >(),
  listRaces: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Race>>
  >(),
  listCharacterClasses: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<CharacterClass>>
  >(),
  listKits: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<Kit>>
  >(),
  listIdentifierDefinitions: vi.fn<
    (query: ListQuery, signal?: AbortSignal) => Promise<ListResult<IdentifierDefinition>>
  >(),
}));

vi.mock(import("./api"), async (importOriginal) => ({
  ...(await importOriginal()),
  getInstallation: api.getInstallation,
  getVoice: api.getVoice,
  getCharacter: api.getCharacter,
  getDialogue: api.getDialogue,
  listCharacters: api.listCharacters,
  listVoices: api.listVoices,
  listDialogues: api.listDialogues,
  listDialogueLines: api.listDialogueLines,
  listExtractionRuns: api.listExtractionRuns,
  listRaces: api.listRaces,
  listCharacterClasses: api.listCharacterClasses,
  listKits: api.listKits,
  listIdentifierDefinitions: api.listIdentifierDefinitions,
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
  source: { kind: SourceKind.OVERRIDE, path: "D:\\Games\\BG\\BG2EE-EET\\override\\imoen.cre" },
  extraction: { status: DetailStatus.COMPLETE },
  attributionStatus: AttributionStatus.PARTIAL_MATCH,
  serializedSize: 6042n,
  dialogue: {
    declaredDialogueCount: 7,
    resolvedDialogueCount: 5,
    npcLineCount: 7563n,
    playerLineCount: 5009n,
    stateCount: 7563n,
    transitionCount: 17309n,
  },
  detail: {
    dialogResref: "imoen",
    genderLabel: "Female",
    raceLabel: "Human",
    classLabel: "Thief",
    alignmentLabel: "Neutral Good",
    kitIdsValue: 16384,
    kitLabel: "Trueclass",
    creKitValue: 0x40000000,
    baseAttributes: {
      strength: 9,
      intelligence: 17,
      wisdom: 11,
      dexterity: 18,
      constitution: 16,
      charisma: 16,
    },
    creVersion: "V1.0",
  },
  directDialogue: "installations/bg2ee-eet/dialogues/imoen-dlg-dc9ebab9",
  biography: "installations/bg2ee-eet/characterSounds/imoen-cre-74-bb456c9b",
});

const dialogue = create(DialogueSchema, {
  name: "installations/bg2ee-eet/dialogues/imoen2j-dlg-789f493a",
  engineResourceName: "IMOEN2J.DLG",
  resref: "IMOEN2J",
  source: { kind: SourceKind.OVERRIDE, path: "D:\\Games\\BG\\BG2EE-EET\\override\\IMOEN2J.DLG" },
  extraction: { status: DetailStatus.COMPLETE },
  serializedSize: 6_082_560n,
  characterCount: 15,
  detail: {
    dlgVersion: "V1.0",
    dialogueLineCount: 9_764n,
    npcLineCount: 5_788n,
    playerLineCount: 3_976n,
    journalLineCount: 71n,
    stateCount: 5_788n,
    transitionCount: 13_861n,
  },
  directedLineCount: 100n,
  generatedAudioCount: 92n,
});

const line = create(DialogueLineSchema, {
  name: "installations/bg2ee-eet/dialogueLines/imoen2j-dlg-0-0-ecdf1e0b",
  dialogue: "installations/bg2ee-eet/dialogues/imoen2j-dlg-789f493a",
  dialogueResref: "IMOEN2J",
  sourceKind: SourceKind.OVERRIDE,
  lineKind: DialogueLineKind.NPC,
  stateIndex: 42,
  transitionIndex: 7,
  strref: 18_421,
  characterCount: 3,
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

const race = create(RaceSchema, {
  name: "installations/bg2ee-eet/races/r-1-245bda1b",
  raceId: 1,
  symbols: ["HUMAN"],
  displayName: "human",
  texts: [{
    sourceResource: "RACETEXT.2DA",
    campaigns: ["SOA", "TOB"],
    rowName: "HUMAN",
    nameStrref: 7_193,
    displayName: "human",
    descriptionStrref: 9_550,
    description: "Humans are adaptable and ambitious.",
    biographyStrref: 21_023,
    biography: "Raised in Candlekeep under Gorion's care.",
  }],
});

const characterClass = create(CharacterClassSchema, {
  name: "installations/bg2ee-eet/characterClasses/r-3-e17e7eb2",
  classId: 3,
  symbols: ["CLERIC"],
  displayName: "Cleric",
  texts: [{
    sourceResource: "CLASTEXT.2DA",
    campaigns: ["SOA", "TOB"],
    rowName: "CLERIC",
    classTextKitId: 16_384,
    lowerNameStrref: 7_200,
    lowerName: "cleric",
    mixedNameStrref: 7_201,
    mixedName: "Cleric",
    descriptionStrref: 7_202,
    description: "A divine spellcaster and armored healer.",
    briefDescriptionStrref: 7_203,
    briefDescription: "Divine spellcaster",
    fallen: false,
  }],
});

const kit = create(KitSchema, {
  name: "installations/bg2ee-eet/kits/r-1-f4341954",
  rowId: 1,
  rowName: "BERSERKER",
  sourceResource: "KITLIST.2DA",
  lowerName: "berserker",
  mixedName: "Berserker",
  displayName: "Berserker",
  helpText: "A warrior who channels a controlled battle rage.",
  characterClass: characterClass.name,
  classSymbols: ["FIGHTER", "FIGHTER_ALL"],
  kitIdsValue: 0x4001,
  kitSymbols: ["BERSERKER"],
  abilitiesResref: "CLABFI02",
  proficiencyColumn: 29,
  unusableMask: 1,
});

const identifier = create(IdentifierDefinitionSchema, {
  name: "installations/bg2ee-eet/identifierDefinitions/gender-1-ea93ad84",
  kind: IdentifierKind.GENDER,
  value: 1,
  symbols: ["MALE"],
  sourceResource: "GENDER.IDS",
  displayName: "Male",
});

beforeEach(() => {
  vi.resetAllMocks();
  api.getInstallation.mockResolvedValue(installation);
  api.listVoices.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 1n });
  api.getVoice.mockResolvedValue(voice);
  api.getCharacter.mockResolvedValue(character);
  api.getDialogue.mockResolvedValue(dialogue);
  api.listCharacters.mockResolvedValue({ items: [character], nextPageToken: "", totalSize: 1n });
  api.listDialogues.mockResolvedValue({ items: [dialogue], nextPageToken: "", totalSize: 1n });
  api.listDialogueLines.mockResolvedValue({ items: [line], nextPageToken: "", totalSize: 1n });
  api.listExtractionRuns.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
  api.listRaces.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
  api.listCharacterClasses.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
  api.listKits.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
  api.listIdentifierDefinitions.mockResolvedValue({ items: [], nextPageToken: "", totalSize: 0n });
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("application jobs", () => {
  it("finds a voice without loading its detail and preserves the collection query", async () => {
    api.listVoices.mockResolvedValue({ items: [voice], nextPageToken: "", totalSize: 1n });
    window.history.replaceState(null, "", "/voices?page_size=50");
    const user = userEvent.setup();
    render(<App />);

    const name = await screen.findByText("Imoen");
    const link = name.closest("a");
    expect(link?.getAttribute("href")).toBe("/voices/imoen?page_size=50");
    expect(api.getVoice).not.toHaveBeenCalled();

    await user.click(link!);
    expect(await screen.findByRole("heading", { name: "Imoen", level: 1 })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to voices" }).getAttribute("href"))
      .toBe("/voices?page_size=50");
  });

  it("reviews a voice and follows its highest-workload character", async () => {
    window.history.replaceState(null, "", "/voices/imoen");
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Imoen", level: 1 })).toBeTruthy();
    expect(api.getVoice).toHaveBeenCalledWith(voice.name, expect.any(AbortSignal));
    expect(api.listVoices).not.toHaveBeenCalled();
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

  it("browses exact CRE variants and preserves the collection query", async () => {
    window.history.replaceState(null, "", "/characters?page_size=50");
    const user = userEvent.setup();
    render(<App />);

    const link = await screen.findByRole("link", { name: "Imoen, IMOEN.CRE" });
    expect(link.getAttribute("href")).toBe("/characters/imoen-cre-3768424f?page_size=50");
    expect(screen.queryByRole("spinbutton", { name: "Gender ID" })).toBeNull();
    expect(api.listCharacters).toHaveBeenCalledWith(
      expect.objectContaining({ orderBy: "npc_line_count desc", pageSize: 50 }),
      expect.any(AbortSignal),
    );

    await user.click(link);
    expect(await screen.findByRole("heading", { name: "Imoen", level: 1 })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to characters" }).getAttribute("href"))
      .toBe("/characters?page_size=50");
    const workload = within(screen.getByLabelText("Character dialogue workload"));
    expect(workload.getAllByText("7,563")).toHaveLength(2);
    expect(workload.getByText("5 of 7")).toBeTruthy();
  });

  it("reviews dialogue content, graph, and generated work without false coverage", async () => {
    window.history.replaceState(null, "", "/dialogues?page_size=50");
    const user = userEvent.setup();
    render(<App />);

    const link = await screen.findByRole("link", {
      name: "IMOEN2J.DLG, imoen2j-dlg-789f493a",
    });
    expect(link.getAttribute("href")).toBe("/dialogues/imoen2j-dlg-789f493a?page_size=50");
    expect(screen.getByRole("link", { name: "5,788 NPC lines" })).toBeTruthy();
    expect(screen.getByText("13,861 transitions")).toBeTruthy();
    expect(api.listDialogues).toHaveBeenCalledWith(
      expect.objectContaining({ orderBy: "npc_line_count desc", pageSize: 50 }),
      expect.any(AbortSignal),
    );

    await user.click(link);
    expect(await screen.findByRole("heading", { name: "IMOEN2J.DLG", level: 1 })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to dialogues" }).getAttribute("href"))
      .toBe("/dialogues?page_size=50");

    const generated = within(screen.getByRole("region", { name: "Generated work" }));
    expect(generated.getByText("Audio lines").previousElementSibling?.textContent).toBe("92");
    expect(generated.getByText("Directed lines").previousElementSibling?.textContent).toBe("100");
    expect(screen.queryByText("Awaiting TTS")).toBeNull();
    expect(screen.queryByText(/source lines/i)).toBeNull();

    const npcUrl = new URL(
      screen.getAllByRole("link", { name: "Browse NPC lines" })[0]!.getAttribute("href") ?? "",
      window.location.origin,
    );
    expect(npcUrl.pathname).toBe("/dialogue-lines/npc");
    expect(npcUrl.searchParams.get("filter"))
      .toBe('dialogue_resource_name = "IMOEN2J.DLG"');
    const transitionUrl = new URL(
      screen.getByRole("link", { name: "Browse transitions →" }).getAttribute("href") ?? "",
      window.location.origin,
    );
    expect(transitionUrl.pathname).toBe("/dialogue-transitions");
    expect(transitionUrl.searchParams.get("filter"))
      .toBe('dialogue_resource_name = "IMOEN2J.DLG"');
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

    const href = (await screen.findByRole("link", { name: "All NPC lines" })).getAttribute("href");
    const url = new URL(href ?? "", window.location.origin);
    expect(url.pathname).toBe("/dialogue-lines/npc");
    expect(url.searchParams.get("filter")).toBe('voice_id = "armored figure"');
  });

  it("reviews NPC delivery and keeps line kinds as distinct workspaces", async () => {
    window.history.replaceState(null, "", "/dialogue-lines/npc");
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "NPC lines", level: 1 })).toBeTruthy();
    expect(screen.getByText(line.text ?? "")).toBeTruthy();
    const context = within(screen.getByLabelText("Dialogue tokens"));
    expect(context.getAllByText(/./).map((token) => token.textContent)).toEqual([
      "CHARNAME×3", "PLAYER1×2", "PLAYER2×2", "DAY",
    ]);
    expect(screen.getByText("[brightly] Heya! It's me, Imoen!")).toBeTruthy();
    expect(screen.getByText("[narrate gently] The chamber falls silent.")).toBeTruthy();
    const audio = screen.getByLabelText("Audio sample for Imoen");
    expect(audio.getAttribute("preload")).toBe("none");
    expect(audio.getAttribute("src")).toBe(line.directions[0]?.audioUrl);
    expect(screen.getByLabelText("Narrator audio sample attributed to Imoen")).toBeTruthy();
    expect(api.listDialogueLines).toHaveBeenCalledWith(
      expect.objectContaining({ filter: 'line_kind = "npc"', orderBy: "dialogue asc", pageSize: 25 }),
      expect.any(AbortSignal),
    );

    await user.click(screen.getAllByRole("link", { name: "Player lines" })[0]!);
    expect(await screen.findByRole("heading", { name: "Player lines", level: 1 })).toBeTruthy();
    expect(screen.queryByText("Voice ID")).toBeNull();
    expect(api.listDialogueLines).toHaveBeenLastCalledWith(
      expect.objectContaining({ filter: 'line_kind = "player"', orderBy: "dialogue asc" }),
      expect.any(AbortSignal),
    );
  });

  it("reads canonical definitions and their engine provenance", async () => {
    api.listRaces.mockResolvedValue({ items: [race], nextPageToken: "", totalSize: 1n });
    api.listCharacterClasses.mockResolvedValue({
      items: [characterClass],
      nextPageToken: "",
      totalSize: 1n,
    });
    api.listKits.mockResolvedValue({ items: [kit], nextPageToken: "", totalSize: 1n });
    api.listIdentifierDefinitions.mockResolvedValue({
      items: [identifier],
      nextPageToken: "",
      totalSize: 1n,
    });
    window.history.replaceState(null, "", "/definitions/races");
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Races", level: 1 })).toBeTruthy();
    await user.selectOptions(screen.getByRole("combobox", { name: "Order" }), "display_name asc");
    await waitFor(() => expect(api.listRaces).toHaveBeenLastCalledWith(
      expect.objectContaining({ orderBy: "display_name asc" }),
      expect.any(AbortSignal),
    ));
    await user.click(screen.getByText("human", { selector: ".definition-card-title strong" }));
    expect(screen.getByText("Description · #9550")).toBeTruthy();
    expect(screen.getByText("Raised in Candlekeep under Gorion's care.")).toBeTruthy();
    expect(screen.getByText("RACETEXT.2DA")).toBeTruthy();

    await user.click(screen.getAllByRole("link", { name: "Classes" })[0]!);
    expect(await screen.findByRole("heading", { name: "Character classes", level: 1 }))
      .toBeTruthy();
    await user.click(screen.getByText("Cleric", { selector: ".definition-card-title strong" }));
    expect(screen.getByText("CLASTEXT kit 16384")).toBeTruthy();
    expect(screen.getByText("Not fallen", { selector: ".definition-tags span" })).toBeTruthy();
    expect(screen.getByText("A divine spellcaster and armored healer.")).toBeTruthy();

    await user.click(screen.getAllByRole("link", { name: "Kits" })[0]!);
    expect(await screen.findByRole("heading", { name: "Kits", level: 1 })).toBeTruthy();
    await user.click(screen.getByText("Berserker", { selector: ".definition-card-title strong" }));
    expect(screen.getAllByText("FIGHTER · FIGHTER ALL").length).toBeGreaterThan(0);
    expect(screen.getByText("A warrior who channels a controlled battle rage.")).toBeTruthy();
    expect(screen.getByText("CLABFI02")).toBeTruthy();
    expect(screen.getAllByText("0x00004001")).toHaveLength(2);
    expect(screen.getByText(characterClass.name)).toBeTruthy();

    await user.click(screen.getAllByRole("link", { name: "Identifiers" })[0]!);
    expect(await screen.findByRole("heading", { name: "Identifiers", level: 1 })).toBeTruthy();
    expect(screen.getByText("0x00000001")).toBeTruthy();
    expect(screen.getByText("GENDER.IDS")).toBeTruthy();
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind" }), "gender");
    await waitFor(() => expect(api.listIdentifierDefinitions).toHaveBeenLastCalledWith(
      expect.objectContaining({ filter: 'kind = "gender"' }),
      expect.any(AbortSignal),
    ));
  });

  it("summarizes the pipeline and opens extraction history on demand", async () => {
    window.history.replaceState(null, "", "/pipeline");
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href"))
      .toBe("#main-content");
    const output = within(await screen.findByRole("region", { name: "Generated output" }));
    expect(output.getByText("Voice assignments").nextElementSibling?.textContent).toBe("7");
    expect(output.getByText("Unique Inworld voices").nextElementSibling?.textContent).toBe("3");

    const corpus = within(screen.getByRole("region", { name: "Dialogue corpus" }));
    expect(corpus.getByText("20")).toBeTruthy();
    expect(corpus.getByRole("img", { name: "NPC 11, Player 7, Journal 2" })).toBeTruthy();

    expect(screen.getByRole("heading", { name: "3 dialogue lines need direction" })).toBeTruthy();
    const health = within(screen.getByLabelText("Generation health"));
    expect(health.getByText("Voice creation").nextElementSibling?.textContent).toBe("1");
    expect(health.getByText("Audio generation").nextElementSibling?.textContent).toBe("6");
    expect(api.listExtractionRuns).not.toHaveBeenCalled();
    expect(screen.getAllByRole("link", { name: "Pipeline", current: "page" })).toHaveLength(2);

    await user.click(screen.getAllByRole("link", { name: "Extraction runs" })[0]!);
    await waitFor(() => expect(window.location.pathname).toBe("/extraction-runs"));
    await waitFor(() => expect(document.title).toBe("Extraction runs · BGVoice"));
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(screen.getAllByRole("link", { name: "Extraction runs", current: "page" })).toHaveLength(2);
    expect(await screen.findByRole("heading", { name: "Extraction runs", level: 1 })).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "Full-text search runs" })).toBeTruthy();
    expect(api.listExtractionRuns).toHaveBeenCalledOnce();
  });
});
