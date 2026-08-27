import { create } from "@bufbuild/protobuf";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LineContext } from "./DialogueLines";
import { VoiceLink } from "./resource-ui";
import { VoiceSchema } from "./gen/bgvoice/v1/pipeline_pb";
import {
  ResourceLinks,
  VoiceAvatar,
  VoiceCard,
  VoiceDetail,
} from "./VoiceBrowser";
import { ScriptText, SoundSlot } from "./SourceBrowsers";

const voice = create(VoiceSchema, {
  name: "installations/bg2ee-eet/voices/imoen",
  voiceId: "imoen",
  displayName: "Imoen",
  prompt: "Warm, quick-witted and mischievous. Keep an easy Amnian cadence.",
  characters: [
    {
      name: "installations/bg2ee-eet/characters/IMOEN.CRE",
      engineResourceName: "IMOEN.CRE",
      displayName: "Imoen",
      npcLineCount: 6108n,
    },
    {
      name: "installations/bg2ee-eet/characters/IMOEN15.CRE",
      engineResourceName: "IMOEN15.CRE",
      displayName: "Imoen",
      npcLineCount: 812n,
    },
  ],
  dialogues: [
    {
      name: "installations/bg2ee-eet/dialogues/IMOEN2J.DLG",
      engineResourceName: "IMOEN2J.DLG",
      npcLineCount: 5758n,
    },
  ],
  portrait: "installations/bg2ee-eet/portraits/NIMOENL",
  biography: "installations/bg2ee-eet/characterSounds/imoen-biography",
  characterCount: 2,
  dialogueCount: 1,
  npcLineCount: 6108n,
  serializedSize: 912n,
});

describe("voice workspace", () => {
  it("uses a lazy portrait with a visible initials fallback", () => {
    const html = renderToStaticMarkup(<VoiceAvatar voice={voice} />);

    expect(html).toContain("IM");
    expect(html).toContain('loading="lazy"');
    expect(html).toContain(
      "/v1/installations/bg2ee-eet/portraits/NIMOENL:download",
    );
  });

  it("deep-links cards by canonical resource name", () => {
    const html = renderToStaticMarkup(
      <VoiceCard voice={voice} selected search="?page_size=50" />,
    );

    expect(html).toContain(
      'href="/voices/imoen?page_size=50"',
    );
    expect(html).toContain('aria-current="page"');
    expect(html).toContain("6,108 NPC lines");
  });

  it("keeps the prompt and source resources visible in voice detail", () => {
    const html = renderToStaticMarkup(
      <VoiceDetail
        voice={voice}
        requestedId={voice.name}
        error={null}
        search="?filter=search%28%22imoen%22%29"
      />,
    );

    expect(html).toContain(voice.prompt);
    expect(html).toContain("IMOEN.CRE");
    expect(html).toContain("IMOEN2J.DLG");
    expect(html).toContain("VOICE CREATION PROMPT");
    expect(html).toContain("Includes imoen-biography");
    expect(html).toContain(
      'href="/voices?filter=search%28%22imoen%22%29"',
    );
  });

  it("renders canonical character and dialogue links rather than chips", () => {
    const characters = renderToStaticMarkup(
      <ResourceLinks title="Characters" references={voice.characters} kind="character" />,
    );
    const dialogues = renderToStaticMarkup(
      <ResourceLinks title="Dialogues" references={voice.dialogues} kind="dialogue" />,
    );

    expect(characters).toContain(
      "/characters/IMOEN.CRE",
    );
    expect(characters).toContain(">IMOEN × 6,108</a>");
    expect(characters.indexOf("IMOEN × 6,108")).toBeLessThan(
      characters.indexOf("IMOEN15 × 812"),
    );
    expect(dialogues).toContain(
      "/dialogues/IMOEN2J.DLG",
    );
    expect(dialogues).toContain(">IMOEN2J × 5,758</a>");
  });
});

describe("pipeline context labels", () => {
  it("shows sound-slot aliases and every matching SPEECH group", () => {
    const html = renderToStaticMarkup(
      <SoundSlot
        slotId={9}
        symbols={["BATTLE_CRY", "ATTACK"]}
        groups={["BATTLE_CRIES", "COMBAT_VOICE"]}
      />,
    );

    expect(html).toContain("BATTLE CRY");
    expect(html).toContain("ATTACK");
    expect(html).toContain("SPEECH · BATTLE CRIES, COMBAT VOICE");
  });

  it("keeps unresolved transition and state-trigger indexes visible", () => {
    expect(
      renderToStaticMarkup(
        <ScriptText index={17} text={undefined} empty="Unconditional" />,
      ),
    ).toContain("Index 17 · unresolved");
    expect(
      renderToStaticMarkup(
        <LineContext tokens={[]} triggerIndex={23} triggerText={undefined} />,
      ),
    ).toContain("State trigger 23 · unresolved");
  });

  it("deduplicates context and orders it by descending occurrence count", () => {
    const html = renderToStaticMarkup(
      <LineContext
        tokens={[
          "PLAYER2",
          "CHARNAME",
          "DAY",
          "PLAYER1",
          "CHARNAME",
          "PLAYER2",
          "CHARNAME",
          "PLAYER1",
        ]}
        triggerIndex={undefined}
        triggerText={undefined}
      />,
    );

    expect(html.match(/CHARNAME/g)).toHaveLength(1);
    expect(html).toContain("CHARNAME×3");
    expect(html).toContain("PLAYER1×2");
    expect(html).toContain("PLAYER2×2");
    expect(html.indexOf("CHARNAME")).toBeLessThan(html.indexOf("PLAYER1"));
    expect(html.indexOf("PLAYER1")).toBeLessThan(html.indexOf("PLAYER2"));
    expect(html.indexOf("PLAYER2")).toBeLessThan(html.indexOf("DAY"));
  });

  it("links characters to their canonical voice resource", () => {
    const html = renderToStaticMarkup(<VoiceLink voice={voice.name} />);

    expect(html).toContain(
      'href="/voices/imoen"',
    );
    expect(html).toContain("imoen");
  });
});
