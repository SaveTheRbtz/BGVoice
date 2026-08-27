import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LineContext } from "./App";
import { ScriptText, SoundSlot } from "./PipelineBrowsers";

describe("pipeline context labels", () => {
  it("shows every matching SPEECH group beside the sound-slot identity", () => {
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
});
