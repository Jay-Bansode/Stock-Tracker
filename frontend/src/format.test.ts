import { describe, expect, it } from "vitest";
import { dayChangePct, distancePct, formatINR, formatIST, formatPct } from "./format";

describe("format", () => {
  it("formats rupees with Indian grouping", () => {
    expect(formatINR(1500)).toBe("₹1,500");
    expect(formatINR(1502.35)).toBe("₹1,502.35");
    expect(formatINR(150000.5)).toBe("₹1,50,000.50");
    expect(formatINR(null)).toBe("—");
  });

  it("formats IST timestamps", () => {
    expect(formatIST("2026-10-29T05:12:15Z")).toMatch(/29 Oct 2026.*10:42:15 IST/);
  });

  it("computes percentages", () => {
    expect(formatPct(dayChangePct(1502, 1490))).toBe("+0.81%");
    expect(formatPct(distancePct(1470, 1500))).toBe("+2.04%");
    expect(distancePct(undefined, 1500)).toBeNull();
  });
});
