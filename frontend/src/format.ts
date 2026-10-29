const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2, minimumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** ₹1,500 for whole rupees, ₹1,502.35 otherwise (Indian digit grouping). */
export function formatINR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? inr.format(value) : inr2.format(value);
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
