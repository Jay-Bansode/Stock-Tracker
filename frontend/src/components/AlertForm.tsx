import { useState, type FormEvent } from "react";
import { formatINR, formatLTP } from "../format";
import type { Alert, AlertInput, Condition, TriggerMode } from "../types";

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

  const targetNum = Number(target);
  const valid = target !== "" && Number.isFinite(targetNum) && targetNum > 0;
  const alreadyMet =
    valid && ltp !== undefined && (condition === "ABOVE" ? ltp >= targetNum : ltp <= targetNum);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    onSubmit({
      condition,
      target_price: Math.round(targetNum * 100) / 100,
      trigger_mode: mode,
      rearm_pct: Number(rearmPct) || 0,
      cooldown_sec: Math.round((Number(cooldownMin) || 0) * 60),
      note: note.trim() || null,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Alert when price is</span>
          <select className="input w-40" value={condition} onChange={(e) => setCondition(e.target.value as Condition)}>
            <option value="ABOVE">At or above (≥)</option>
            <option value="BELOW">At or below (≤)</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Target price (₹)</span>
          <input
            className="input num w-36"
            inputMode="decimal"
            autoFocus
            placeholder={ltp ? ltp.toFixed(2) : "1500"}
            value={target}
            onChange={(e) => setTarget(e.target.value.replace(/[^0-9.]/g, ""))}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Repeat</span>
          <select className="input w-44" value={mode} onChange={(e) => setMode(e.target.value as TriggerMode)}>
            <option value="ONCE">Once (re-arm manually)</option>
            <option value="REPEAT">Re-arm automatically</option>
          </select>
        </label>
        {mode === "REPEAT" && (
          <>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500" title="Price must move back this far past the target before the alert can fire again">
                Re-arm band (%)
              </span>
              <input className="input num w-24" inputMode="decimal" value={rearmPct} onChange={(e) => setRearmPct(e.target.value)} />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">Cooldown (min)</span>
              <input className="input num w-24" inputMode="numeric" value={cooldownMin} onChange={(e) => setCooldownMin(e.target.value)} />
            </label>
          </>
        )}
        <label className="block min-w-48 flex-1">
          <span className="mb-1 block text-xs font-medium text-slate-500">Note (optional)</span>
          <input className="input" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. breakout above resistance" />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">
          Current price: <span className="num font-medium text-slate-700 dark:text-slate-200">{formatLTP(ltp)}</span>
        </span>
        {alreadyMet && (
          <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            Price is already {condition === "ABOVE" ? "at or above" : "at or below"} {formatINR(targetNum)}. This alert will fire on the next tick.
          </span>
        )}
      </div>

      {error ? <p className="text-sm text-red-600">{error instanceof Error ? error.message : String(error)}</p> : null}

      <div className="flex gap-2">
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
