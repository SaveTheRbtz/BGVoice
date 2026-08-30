// @vitest-environment jsdom

import { create } from "@bufbuild/protobuf";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as apiModule from "./api";
import App from "./App";
import {
  AttributionStatus,
  CharacterClassSchema,
  CharacterSchema,
  CharacterSoundSchema,
  DetailStatus,
  DialogueLineKind,
  DialogueLineSchema,
  DialogueSchema,
  DialogueTransitionSchema,
  ExtractionRunSchema,
  IdentifierDefinitionSchema,
  IdentifierKind,
  InstallationSchema,
  KitSchema,
  ProviderGender,
  RaceSchema,
  ReadableItemKind,
  ReadableItemSchema,
  RunKind,
  RunStatus,
  SourceKind,
  VoiceProfileKind,
  VoiceSchema,
} from "./gen/bgvoice/v1/pipeline_pb";

vi.mock(import("./api"));
const api = vi.mocked(apiModule);

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
  name: "installations/bg2ee-eet/voices/imoen-befd8070",
  voiceId: "imoen",
  familyId: "imoen",
  gender: ProviderGender.FEMALE,
  displayName: "Imoen",
  prompt: "Warm, quick-witted and mischievous.",
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
    profileId: "imoen",
    profileKind: VoiceProfileKind.DEDICATED,
    description: "Youthful, warm and quick-witted.",
    inworldVoiceId: "voice-imoen",
  },
});

const character = create(CharacterSchema, {
  name: "installations/bg2ee-eet/characters/imoen-cre-3768424f",
  engineResourceName: "IMOEN.CRE",
  resref: "IMOEN",
  displayName: "Imoen",
  voice: voice.name,
  source: { kind: SourceKind.OVERRIDE, path: "D:\\Games\\BG\\override\\IMOEN.CRE" },
  extraction: { status: DetailStatus.COMPLETE },
  attributionStatus: AttributionStatus.PARTIAL_MATCH,
  dialogue: {
    declaredDialogueCount: 7,
    resolvedDialogueCount: 5,
    npcLineCount: 7563n,
    stateCount: 7563n,
  },
});

const dialogue = create(DialogueSchema, {
  name: "installations/bg2ee-eet/dialogues/imoen2j-dlg-789f493a",
  engineResourceName: "IMOEN2J.DLG",
  resref: "IMOEN2J",
  source: { kind: SourceKind.OVERRIDE, path: "D:\\Games\\BG\\override\\IMOEN2J.DLG" },
  extraction: { status: DetailStatus.COMPLETE },
  detail: {
    npcLineCount: 5788n,
    playerLineCount: 3976n,
    journalLineCount: 71n,
    transitionCount: 13_861n,
  },
  directedLineCount: 100n,
  generatedAudioCount: 92n,
});

const line = create(DialogueLineSchema, {
  name: "installations/bg2ee-eet/dialogueLines/imoen2j-dlg-0-0-ecdf1e0b",
  dialogue: dialogue.name,
  dialogueResref: "IMOEN2J",
  sourceKind: SourceKind.OVERRIDE,
  lineKind: DialogueLineKind.NPC,
  stateIndex: 42,
  transitionIndex: 7,
  text: "Heya! It's me, Imoen!",
  tokens: ["PLAYER2", "CHARNAME", "DAY", "PLAYER1", "CHARNAME", "PLAYER2", "CHARNAME", "PLAYER1"],
  directions: [{
    id: "direction-1",
    voice: voice.name,
    voiceDisplayName: "Imoen",
    result: { case: "character", value: { directedDialogue: "[brightly] Heya! It's me, Imoen!" } },
    audioUrl: "/v1/installations/bg2ee-eet/generatedAudio/audio-1:download",
  }, {
    id: "direction-2",
    voice: voice.name,
    voiceDisplayName: "Imoen",
    result: { case: "narrator", value: { directedDialogue: "[gently] The chamber falls silent." } },
    audioUrl: "/v1/installations/bg2ee-eet/generatedAudio/audio-2:download",
  }],
});

const race = create(RaceSchema, {
  name: "installations/bg2ee-eet/races/r-1-245bda1b",
  raceId: 1,
  symbols: ["HUMAN"],
  displayName: "Human",
  campaignTexts: [{
    sourceResource: "RACETEXT.2DA",
    rowName: "HUMAN",
    description: "Humans are adaptable and ambitious.",
  }],
});

const characterClass = create(CharacterClassSchema, {
  name: "installations/bg2ee-eet/characterClasses/r-3-e17e7eb2",
  classId: 3,
  symbols: ["CLERIC"],
  displayName: "Cleric",
  texts: [{
    sourceResource: "CLASTEXT.2DA",
    rowName: "CLERIC",
    description: "A divine spellcaster and armored healer.",
  }],
});

const kit = create(KitSchema, {
  name: "installations/bg2ee-eet/kits/r-1-f4341954",
  rowId: 1,
  rowName: "BERSERKER",
  sourceResource: "KITLIST.2DA",
  displayName: "Berserker",
  helpText: "A warrior who channels a controlled battle rage.",
  characterClass: characterClass.name,
  classSymbols: ["FIGHTER"],
  kitIdsValue: 0x4001,
});

const identifier = create(IdentifierDefinitionSchema, {
  name: "installations/bg2ee-eet/identifierDefinitions/gender-1-ea93ad84",
  kind: IdentifierKind.GENDER,
  value: 1,
  symbols: ["MALE"],
  sourceResource: "GENDER.IDS",
  displayName: "Male",
});

function page<T>(...items: T[]) {
  return { items, nextPageToken: "", totalSize: BigInt(items.length) };
}

function renderRoute(path: string) {
  const user = userEvent.setup();
  window.history.replaceState(null, "", path);
  render(<App />);
  return user;
}

function summaryContaining(text: string): HTMLElement {
  const summary = screen.getAllByText(text, { exact: true })
    .map((element) => element.closest("summary"))
    .find((element): element is HTMLElement => element != null);
  expect(summary).toBeDefined();
  return summary!;
}

beforeEach(() => {
  vi.resetAllMocks();
  api.getInstallation.mockResolvedValue(installation);
  api.listVoices.mockResolvedValue(page());
  api.getVoice.mockResolvedValue(voice);
  api.getCharacter.mockResolvedValue(character);
  api.getDialogue.mockResolvedValue(dialogue);
  api.listCharacters.mockResolvedValue(page(character));
  api.listDialogues.mockResolvedValue(page(dialogue));
  api.listDialogueLines.mockResolvedValue(page(line));
  api.listDialogueTransitions.mockResolvedValue(page());
  api.listCharacterSounds.mockResolvedValue(page());
  api.listExtractionRuns.mockResolvedValue(page());
  api.listRaces.mockResolvedValue(page());
  api.listCharacterClasses.mockResolvedValue(page());
  api.listKits.mockResolvedValue(page());
  api.listIdentifierDefinitions.mockResolvedValue(page());
  api.listReadableItems.mockResolvedValue(page());
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("application workflows", () => {
  it.for([
    {
      path: "/character-sounds",
      seed: () => api.listCharacterSounds.mockResolvedValue(page(create(CharacterSoundSchema, {
        name: `${character.name}/sounds/74`,
        character: character.name,
        characterDisplayName: "Imoen",
        slotId: 74,
        slotGroups: ["BIO"],
        text: "Imoen grew up in Candlekeep.",
      }))),
      fact: "Biography",
    },
    {
      path: "/dialogue-transitions",
      seed: () => api.listDialogueTransitions.mockResolvedValue(page(create(
        DialogueTransitionSchema,
        {
          name: `${dialogue.name}/transitions/42-7`,
          dialogue: dialogue.name,
          dialogueResref: "IMOEN2J",
          sourceKind: SourceKind.OVERRIDE,
          stateIndex: 42,
          transitionIndex: 7,
          actionText: 'SetGlobal("Quest","GLOBAL",1)',
          flagsDecoded: ["HAS_ACTION"],
        },
      ))),
      fact: "HAS ACTION",
    },
    {
      path: "/readable-items",
      seed: () => api.listReadableItems.mockResolvedValue(page(create(ReadableItemSchema, {
        name: "installations/bg2ee-eet/readableItems/book50",
        engineResourceName: "BOOK50.ITM",
        kind: ReadableItemKind.BOOK,
        displayTitle: "History of the North VIII",
        text: "The tumultuous climate continued.",
        textLength: 32n,
      }))),
      fact: "History of the North VIII",
    },
  ])("renders the domain fact '$fact'", async ({ path, seed, fact }) => {
    seed();
    renderRoute(path);
    await screen.findByText(fact);
  });

  it("follows stable voice identities into characters and dialogue lines", async () => {
    api.listVoices.mockResolvedValue(page(voice));
    const user = renderRoute("/voices?page_size=50");

    const voiceLink = await screen.findByRole("link", { name: /^Imoen, ready,/ });
    expect(voiceLink.getAttribute("href")).toBe("/voices/imoen-befd8070?page_size=50");
    await user.click(voiceLink);

    await screen.findByRole("heading", { name: "Imoen", level: 1 });
    screen.getByText(voice.prompt);
    screen.getByText(voice.generatedVoice!.description);
    const allLines = new URL(
      screen.getByRole("link", { name: "All NPC lines" }).getAttribute("href")!,
      window.location.origin,
    );
    expect([allLines.pathname, allLines.searchParams.get("filter")])
      .toEqual(["/dialogue-lines/npc", 'voice_id = "imoen"']);
    expect(screen.getAllByRole("link", { name: /^IMOEN(?:15)? ×/ }).map((link) => link.textContent))
      .toEqual(["IMOEN × 6,108", "IMOEN15 × 812"]);

    await user.click(screen.getByRole("link", { name: "IMOEN × 6,108" }));
    await waitFor(() => expect(window.location.pathname).toBe("/characters/imoen-cre-3768424f"));
    await screen.findByRole("heading", { name: "Imoen", level: 1 });
    within(screen.getByLabelText("Character dialogue workload")).getByText("5 of 7");
  });

  it("preserves navigation when a resource cannot load", async () => {
    api.getVoice.mockRejectedValue(new Error("voice unavailable"));
    renderRoute("/voices/imoen-befd8070?page_size=50");

    expect((await screen.findByRole("alert")).textContent).toContain("voice unavailable");
    expect(screen.getByRole("link", { name: "Back to voices" }).getAttribute("href"))
      .toBe("/voices?page_size=50");
  });

  it("reviews generated dialogue and switches between each line workspace", async () => {
    const user = renderRoute("/dialogues?page_size=50");
    await user.click(await screen.findByRole("link", {
      name: "IMOEN2J.DLG, imoen2j-dlg-789f493a",
    }));

    await screen.findByRole("heading", { name: "IMOEN2J.DLG", level: 1 });
    const generated = within(screen.getByRole("region", { name: "Generated work" }));
    generated.getByText("92");
    generated.getByText("100");

    await user.click(screen.getAllByRole("link", { name: "Browse NPC lines" })[0]!);
    await screen.findByRole("heading", { name: "NPC lines", level: 1 });
    expect(within(screen.getByLabelText("Dialogue tokens")).getAllByText(/./)
      .map((token) => token.textContent))
      .toEqual(["CHARNAME×3", "PLAYER1×2", "PLAYER2×2", "DAY"]);
    screen.getByText("[brightly] Heya! It's me, Imoen!");
    screen.getByText("[gently] The chamber falls silent.");
    screen.getByLabelText("Audio sample for Imoen");

    await user.selectOptions(screen.getByRole("combobox", { name: "Order" }), "text_length desc");
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("order_by"))
      .toBe("text_length desc"));

    await user.click(screen.getAllByRole("link", { name: "Player lines" })[0]!);
    await screen.findByRole("heading", { name: "Player lines", level: 1 });
    expect(screen.queryByText("Voice ID")).toBeNull();

    await user.click(screen.getAllByRole("link", { name: "Journal" })[0]!);
    await screen.findByRole("heading", { name: "Journal entries", level: 1 });
  });

  it("shows canonical definition provenance across metadata resources", async () => {
    api.listRaces.mockResolvedValue(page(race));
    api.listCharacterClasses.mockResolvedValue(page(characterClass));
    api.listKits.mockResolvedValue(page(kit));
    api.listIdentifierDefinitions.mockResolvedValue(page(identifier));
    const user = renderRoute("/definitions/races");

    await screen.findByRole("heading", { name: "Races", level: 1 });
    await user.click(summaryContaining("HUMAN"));
    screen.getByText("Humans are adaptable and ambitious.");
    screen.getByText("RACETEXT.2DA");

    await user.click(screen.getAllByRole("link", { name: "Classes" })[0]!);
    await screen.findByRole("heading", { name: "Character classes", level: 1 });
    await screen.findAllByText("CLERIC");
    await user.click(summaryContaining("CLERIC"));
    screen.getByText("A divine spellcaster and armored healer.");

    await user.click(screen.getAllByRole("link", { name: "Kits" })[0]!);
    await screen.findByRole("heading", { name: "Kits", level: 1 });
    await screen.findByText("Berserker");
    await user.click(summaryContaining("Berserker"));
    screen.getByText("A warrior who channels a controlled battle rage.");
    screen.getAllByText("0x00004001");

    await user.click(screen.getAllByRole("link", { name: "Identifiers" })[0]!);
    await screen.findByRole("heading", { name: "Identifiers", level: 1 });
    screen.getByText("GENDER.IDS");
  });

  it("summarizes generation health and opens extraction history", async () => {
    api.listExtractionRuns.mockResolvedValue(page(create(ExtractionRunSchema, {
      name: "installations/bg2ee-eet/extractionRuns/run-1",
      runId: "run-1",
      runKind: RunKind.DIALOGUES,
      status: RunStatus.COMPLETE,
      resourcesDiscovered: 10n,
      detailsExtracted: 10n,
    })));
    const user = renderRoute("/pipeline");

    const output = within(await screen.findByRole("region", { name: "Generated output" }));
    output.getByText("7");
    output.getByText("3");
    screen.getByRole("heading", { name: "3 dialogue lines need direction" });

    await user.click(screen.getAllByRole("link", { name: "Extraction runs" })[0]!);
    await screen.findByRole("heading", { name: "Extraction runs", level: 1 });
    await screen.findByText("run-1");
  });
});
