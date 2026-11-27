const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2, minimumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹1,500 for whole rupees, ₹1,502.35 otherwise (Indian digit grouping). */
export function formatINR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? inr.format(value) : inr2.format(value);
}

/** "15:15:00" -> "3:15 PM". */
export function formatClock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

/** An alert's daily check window: "" (whole market hours), "at 3:15 PM" or "2:30 PM–3:30 PM". */
export function formatWindow(from: string | null, until: string | null): string {
  if (!from || !until) return "";
  return from.slice(0, 5) === until.slice(0, 5) ? `at ${formatClock(from)}` : `${formatClock(from)}–${formatClock(until)}`;
}

/** Live prices always show paise so ticks line up visually. */
export function formatLTP(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return inr2.format(value);
}

export function formatPct(value: number | null | undefined, signed = true): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const s = value.toFixed(2);
  return `${signed && value > 0 ? "+" : ""}${s}%`;
}

const dt = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

export function formatIST(iso: string | number | null | undefined): string {
  if (!iso) return "—";
  return `${dt.format(new Date(iso))} IST`;
}

export function timeAgo(epochSec: number | null | undefined): string {
  if (!epochSec) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSec));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function dayChangePct(ltp: number | undefined, close: number | null | undefined) {
  if (ltp === undefined || !close) return null;
  return ((ltp - close) / close) * 100;
}

/** How far price must move to hit the target, as % of current price (negative = must fall). */
export function distancePct(ltp: number | undefined, target: number) {
  if (ltp === undefined || !ltp) return null;
  return ((target - ltp) / ltp) * 100;
}

export const exchangeOf = (instrumentKey: string) => instrumentKey.split("_")[0];

/** Rough NSE session check in IST (weekdays 09:15–15:30; holidays not known client-side). */
export function inMarketHoursIST(at: Date = new Date()): boolean {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .formatToParts(at)
      .map((p) => [p.type, p.value]),
  );
  if (parts.weekday === "Sat" || parts.weekday === "Sun") return false;
  const minutes = Number(parts.hour) * 60 + Number(parts.minute);
  return minutes >= 9 * 60 + 15 && minutes <= 15 * 60 + 30;
}

/** Today's calendar date in India, "YYYY-MM-DD". */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/**
 * How long a stock has been held, from its buying date ("YYYY-MM-DD") to today:
 * "2y 3m" (months always shown once there's a year, so "28y 0m"), "5m" under a year,
 * "12d" under a month. Whole calendar months (15 Jan → 14 Mar is 1m).
 * "" for no date or a future one.
 */
export function heldFor(boughtOn: string | null | undefined, today: string = todayIST()): string {
  if (!boughtOn || boughtOn > today) return "";
  const [by, bm, bd] = boughtOn.split("-").map(Number);
  const [ty, tm, td] = today.split("-").map(Number);
  let months = (ty - by) * 12 + (tm - bm);
  if (td < bd) months -= 1;
  if (months <= 0) {
    const days = Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(by, bm - 1, bd)) / 86_400_000);
    return `${days}d`;
  }
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return years ? `${years}y ${rest}m` : `${rest}m`;
}

/** "2024-08-12" -> "12 Aug 2024". */
export function formatDate(ymd: string): string {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(Date.UTC(y, m - 1, d));
}
