import { describe, expect, it } from "vitest";
import { dayChangePct, distancePct, formatDate, formatINR, formatIST, formatPct, heldFor, todayIST } from "./format";

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

  it("works out how long a stock has been held", () => {
    const today = "2026-11-27";
    expect(heldFor("2026-11-27", today)).toBe("0d");
    expect(heldFor("2026-11-07", today)).toBe("20d");
    expect(heldFor("2026-10-27", today)).toBe("1m");
    expect(heldFor("2026-10-28", today)).toBe("30d"); // one day short of a month
    expect(heldFor("2025-11-27", today)).toBe("1y 0m"); // months always shown with years
    expect(heldFor("1998-11-11", today)).toBe("28y 0m");
    expect(heldFor("2024-12-27", today)).toBe("1y 11m");
    expect(heldFor("2024-08-12", today)).toBe("2y 3m");
    expect(heldFor("2026-01-31", "2026-02-28")).toBe("28d"); // month-end: not a full month yet
    expect(heldFor("2026-11-28", today)).toBe(""); // future
    expect(heldFor(null, today)).toBe("");
  });

  it("formats dates and today's date in India", () => {
    expect(formatDate("2024-08-12")).toBe("12 Aug 2024");
    expect(todayIST(new Date("2026-11-26T20:00:00Z"))).toBe("2026-11-27"); // 01:30 IST next day
  });
});
