import { useState, type FormEvent } from "react";
import { formatINR, formatLTP, formatWindow } from "../format";
import type { Alert, AlertInput, Condition, TriggerMode } from "../types";

type When = "ALL" | "AT" | "BETWEEN";

function initialWhen(a?: Alert): When {
  if (!a?.check_from || !a.check_until) return "ALL";
  return a.check_from === a.check_until ? "AT" : "BETWEEN";
}

const hhmm = (t: string | null | undefined, fallback: string) => (t ? t.slice(0, 5) : fallback);

interface Props {
  initial?: Alert;
  ltp?: number;
  busy?: boolean;
  error?: unknown;
  onSubmit: (input: AlertInput) => void;
  onCancel: () => void;
  onDelete?: () => void;
}

export function AlertForm({ initial, ltp, busy, error, onSubmit, onCancel, onDelete }: Props) {
  const [condition, setCondition] = useState<Condition>(initial?.condition ?? "ABOVE");
  const [target, setTarget] = useState(initial ? String(initial.target_price) : "");
  const [mode, setMode] = useState<TriggerMode>(initial?.trigger_mode ?? "ONCE");
  const [rearmPct, setRearmPct] = useState(String(initial?.rearm_pct ?? 0.5));
  const [cooldownMin, setCooldownMin] = useState(String((initial?.cooldown_sec ?? 900) / 60));
  const [note, setNote] = useState(initial?.note ?? "");
  const [when, setWhen] = useState<When>(initialWhen(initial));
  const [from, setFrom] = useState(hhmm(initial?.check_from, "15:15"));
  const [until, setUntil] = useState(hhmm(initial?.check_until, "15:30"));

  const timed = when !== "ALL";
  const windowFrom = timed ? from : null;
  const windowUntil = when === "AT" ? from : when === "BETWEEN" ? until : null;
  const windowValid = !timed || (!!windowFrom && !!windowUntil && windowFrom <= windowUntil);

  const targetNum = Number(target);
  const valid = target !== "" && Number.isFinite(targetNum) && targetNum > 0 && windowValid;
  const alreadyMet =
    valid && ltp !== undefined && (condition === "ABOVE" ? ltp >= targetNum : ltp <= targetNum);

  const changeWhen = (w: When) => {
    if (w === "BETWEEN" && when !== "BETWEEN") {
      setFrom("14:30");
      setUntil("15:30");
    } else if (w === "AT" && when !== "AT") setFrom("15:15");
    setWhen(w);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    onSubmit({
      condition,
      target_price: Math.round(targetNum * 100) / 100,
      trigger_mode: timed ? "REPEAT" : mode, // timed alerts are daily checks
      rearm_pct: Number(rearmPct) || 0,
      cooldown_sec: Math.round((Number(cooldownMin) || 0) * 60),
      note: note.trim() || null,
      check_from: windowFrom,
      check_until: windowUntil,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
      <div className="grid grid-cols-2 items-end gap-3 sm:flex sm:flex-wrap">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Alert when price is</span>
          <select className="input sm:w-40" value={condition} onChange={(e) => setCondition(e.target.value as Condition)}>
            <option value="ABOVE">At or above (≥)</option>
            <option value="BELOW">At or below (≤)</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Target price (₹)</span>
          <input
            className="input num sm:w-36"
            inputMode="decimal"
            autoFocus
            placeholder={ltp ? ltp.toFixed(2) : "1500"}
            value={target}
            onChange={(e) => setTarget(e.target.value.replace(/[^0-9.]/g, ""))}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">When to check</span>
          <select className="input sm:w-48" value={when} onChange={(e) => changeWhen(e.target.value as When)}>
            <option value="ALL">Whole market hours</option>
            <option value="AT">Only at a time</option>
            <option value="BETWEEN">Between two times</option>
          </select>
        </label>
        {timed && (
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">{when === "AT" ? "At (IST)" : "From (IST)"}</span>
            <input className="input num sm:w-32" type="time" step={60} min="09:15" max="15:30" required value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
        )}
        {when === "BETWEEN" && (
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Until (IST)</span>
            <input className="input num sm:w-32" type="time" step={60} min="09:15" max="15:30" required value={until} onChange={(e) => setUntil(e.target.value)} />
          </label>
        )}
        {!timed && (
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Repeat</span>
            <select className="input sm:w-44" value={mode} onChange={(e) => setMode(e.target.value as TriggerMode)}>
              <option value="ONCE">Once (re-arm manually)</option>
              <option value="REPEAT">Re-arm automatically</option>
            </select>
          </label>
        )}
        {!timed && mode === "REPEAT" && (
          <>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500" title="Price must move back this far past the target before the alert can fire again">
                Re-arm band (%)
              </span>
              <input className="input num sm:w-24" inputMode="decimal" value={rearmPct} onChange={(e) => setRearmPct(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">Cooldown (min)</span>
              <input className="input num sm:w-24" inputMode="numeric" value={cooldownMin} onChange={(e) => setCooldownMin(e.target.value)} />
            </label>
          </>
        )}
        <label className="col-span-2 block sm:min-w-48 sm:flex-1">
          <span className="mb-1 block text-xs font-medium text-slate-500">Note (optional)</span>
          <input className="input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. breakout above resistance" />
        </label>
      </div>

      {timed && (
        <p className="text-xs text-slate-500">
          {windowValid
            ? `Checked every trading day ${formatWindow(windowFrom, windowUntil)} IST. You get at most one message a day.`
            : "The start time must not be after the end time."}{" "}
          Pick times within market hours (9:15 AM–3:30 PM).
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">
          Current price: <span className="num font-medium text-slate-700 dark:text-slate-200">{formatLTP(ltp)}</span>
        </span>
        {alreadyMet && (
          <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            Price is already {condition === "ABOVE" ? "at or above" : "at or below"} {formatINR(targetNum)}.{" "}
            {timed ? "If it still is during your check time, the alert will fire then." : "This alert will fire on the next tick."}
          </span>
        )}
      </div>

      {error ? <p className="text-sm text-red-600">{error instanceof Error ? error.message : String(error)}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={!valid || busy}>
          {initial ? "Save alert" : "Add alert"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
        {onDelete && (
          <button type="button" className="btn btn-danger ml-auto" onClick={onDelete} disabled={busy}>
            Delete alert
          </button>
        )}
      </div>
    </form>
  );
}
