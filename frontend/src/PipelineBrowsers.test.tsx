import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LineContext, VoiceLink } from "./App";
import {
  ResourceList,
  ScriptText,
  SoundSlot,
  StarterPrompt,
  VoiceIdChip,
} from "./PipelineBrowsers";

describe("pipeline context labels", () => {
  it("shows a readable starter prompt and collapsible grouped resources", () => {
    const html = renderToStaticMarkup(
      <>
        <StarterPrompt value={"Warm, measured alto.\nRestrained Amnian accent."} />
        <ResourceList
          count={2}
          values={["AERIE.CRE", "AERIE10.CRE"]}
          noun="characters"
        />
      </>,
    );

    expect(html).toContain("Warm, measured alto.\nRestrained Amnian accent.");
    expect(html).toContain("2 characters");
    expect(html).toContain("AERIE.CRE");
    expect(html).toContain("AERIE10.CRE");
  });

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
        <ScriptText index={17} text={null} empty="Unconditional" />,
      ),
    ).toContain("Index 17 · unresolved");
    expect(
      renderToStaticMarkup(
        <LineContext tokens={[]} triggerIndex={23} triggerText={null} />,
      ),
    ).toContain("State trigger 23 · unresolved");
  });

  it("groups line context by descending occurrence count", () => {
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
        triggerIndex={null}
        triggerText={null}
      />,
    );

    expect(html.match(/CHARNAME/g)).toHaveLength(1);
    expect(html).toContain("CHARNAME×3");
    expect(html).toContain("PLAYER1×2");
    expect(html).toContain("PLAYER2×2");
    expect(html).not.toContain("DAY×1");
    expect(html.indexOf("CHARNAME")).toBeLessThan(html.indexOf("PLAYER1"));
    expect(html.indexOf("PLAYER1")).toBeLessThan(html.indexOf("PLAYER2"));
    expect(html.indexOf("PLAYER2")).toBeLessThan(html.indexOf("DAY"));
  });

  it("deep-links a character to its canonical voice search", () => {
    const html = renderToStaticMarkup(
      <VoiceLink voiceId="imoen" onOpen={() => undefined} />,
    );

    expect(html).toContain('href="?tab=voices&amp;voice_id=imoen"');
    expect(html).toContain("imoen");
  });

  it("shows an exact voice ID independently from BM25 search", () => {
    const html = renderToStaticMarkup(<VoiceIdChip voiceId="imoen" />);

    expect(html).toContain("Exact voice");
    expect(html).toContain("imoen");
    expect(renderToStaticMarkup(<VoiceIdChip voiceId="" />)).toBe("");
  });
});
