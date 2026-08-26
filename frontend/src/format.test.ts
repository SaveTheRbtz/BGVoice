import { describe, expect, it } from "vitest";

import { formatBytes, formatCount, formatDate } from "./format";

describe("formatters", () => {
  it("distinguishes missing and zero values", () => {
    expect(formatCount(null)).toBe("—");
    expect(formatCount(0)).toBe("0");
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(0)).toBe("0 B");
    expect(formatDate(null)).toBe("In progress");
  });

  it("uses explicit binary unit thresholds", () => {
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(1024)).toBe("1.0 KiB");
    expect(formatBytes(1024 ** 2)).toBe("1.0 MiB");
    expect(formatBytes(1024 ** 3)).toBe("1.0 GiB");
  });

  it("uses stable English number and date formats", () => {
    expect(formatCount(1_234_567)).toBe("1,234,567");
    expect(formatDate("2026-08-26T12:34:00")).toBe("Aug 26, 2026, 12:34 PM");
  });
});
