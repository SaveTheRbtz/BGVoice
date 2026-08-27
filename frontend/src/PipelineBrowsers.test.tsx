import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LineContext, VoiceLink } from "./App";
import {
  ResourceList,
  ScriptText,
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
          noun="variants"
        />
      </>,
    );

    expect(html).toContain("Warm, measured alto.\nRestrained Amnian accent.");
    expect(html).toContain("2 variants");
    expect(html).toContain("AERIE.CRE");
    expect(html).toContain("AERIE10.CRE");
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

  it("deep-links a CRE variant to its canonical voice search", () => {
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
