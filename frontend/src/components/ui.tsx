import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AlertStatus, Condition, NotificationRow } from "../types";
import { formatINR, formatLTP } from "../format";

const statusStyles: Record<AlertStatus, string> = {
  ACTIVE: "bg-teal-50 text-teal-800 ring-teal-600/20 dark:bg-teal-950 dark:text-teal-300",
  TRIGGERED: "bg-amber-50 text-amber-800 ring-amber-600/30 dark:bg-amber-950 dark:text-amber-300",
  DISABLED: "bg-slate-100 text-slate-600 ring-slate-500/20 dark:bg-slate-800 dark:text-slate-400",
};
const statusLabel: Record<AlertStatus, string> = {
  ACTIVE: "Watching",
  TRIGGERED: "Target hit",
  DISABLED: "Disabled",
};

export function StatusBadge({ status }: { status: AlertStatus }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${statusStyles[status]}`}>
      {statusLabel[status]}
    </span>
  );
}

export const conditionSymbol = (c: Condition) => (c === "ABOVE" ? "≥" : "≤");

export function AlertChip({
  condition,
  target,
  status,
  onClick,
}: {
  condition: Condition;
  target: number;
  status: AlertStatus;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${condition === "ABOVE" ? "Price at or above" : "Price at or below"} ${formatINR(target)} — ${statusLabel[status]}`}
      className={`num inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset hover:brightness-95 ${statusStyles[status]} ${status === "DISABLED" ? "line-through" : ""}`}
    >
      {status === "TRIGGERED" && <span aria-hidden>●</span>}
      {conditionSymbol(condition)} {formatINR(target)}
    </button>
  );
}

/** Live price with a brief green/red flash when it changes. */
export function PriceCell({ value }: { value: number | undefined }) {
  const prev = useRef<number | undefined>(value);
  const [flash, setFlash] = useState<"" | "flash-up" | "flash-down">("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (value !== undefined && prev.current !== undefined && value !== prev.current) {
      setFlash(value > prev.current ? "flash-up" : "flash-down");
      setTick((t) => t + 1);
    }
    prev.current = value;
  }, [value]);
  return (
    <span key={tick} className={`num rounded px-1 font-medium ${flash}`}>
      {formatLTP(value)}
    </span>
  );
}

export function ChangeText({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="text-slate-400">—</span>;
  const tone = pct > 0 ? "text-emerald-600 dark:text-emerald-400" : pct < 0 ? "text-red-600 dark:text-red-400" : "text-slate-500";
  return <span className={`num ${tone}`}>{`${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}</span>;
}

const deliveryStyles: Record<NotificationRow["status"], string> = {
  SENT: "text-emerald-700 dark:text-emerald-400",
  PENDING: "text-slate-500",
  SENDING: "text-slate-500",
  FAILED: "text-red-700 dark:text-red-400",
};

export function DeliveryStatus({ row, onRetry }: { row: NotificationRow | undefined; onRetry?: (id: number) => void }) {
  if (!row) return <span className="text-slate-400">—</span>;
  const label = row.status === "SENT" ? "Sent" : row.status === "FAILED" ? "Failed" : row.attempts > 0 ? `Retrying (${row.attempts})` : "Queued";
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`text-xs font-medium ${deliveryStyles[row.status]}`} title={row.last_error ?? undefined}>
        {label}
      </span>
      {row.status === "FAILED" && onRetry && (
        <button className="btn btn-sm" onClick={() => onRetry(row.id)}>
          Retry
        </button>
      )}
    </span>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center dark:border-slate-700">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-sm text-red-600 dark:text-red-400">{error instanceof Error ? error.message : String(error)}</p>;
}
