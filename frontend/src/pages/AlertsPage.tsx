import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import { SortHeader } from "../components/SortHeader";
import { SortSelect } from "../components/SortSelect";
import { conditionSymbol, EmptyState, ErrorText, PriceCell, StatusBadge } from "../components/ui";
import { distancePct, exchangeOf, formatINR, formatIST, formatPct, formatWindow } from "../format";
import { usePrices } from "../prices";
import { sortRows, useSort, type SortColumns } from "../sorting";
import type { AlertStatus, AlertWithContext } from "../types";

type AlertSortKey = "watchlist" | "symbol" | "target" | "ltp" | "to_target" | "status" | "last_hit";
// Status sorts by what needs attention: target hit, then watching, then disabled.
const STATUS_ORDER: Record<AlertStatus, number> = { TRIGGERED: 0, ACTIVE: 1, DISABLED: 2 };
const SORT_OPTIONS: { key: AlertSortKey; label: string; first?: "asc" | "desc" }[] = [
  { key: "watchlist", label: "Watchlist" },
  { key: "symbol", label: "Stock" },
  { key: "target", label: "Target", first: "desc" },
  { key: "ltp", label: "LTP", first: "desc" },
  { key: "to_target", label: "Closest to target" },
  { key: "status", label: "Status" },
  { key: "last_hit", label: "Last hit", first: "desc" },
];

export default function AlertsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<AlertStatus | "">("");
  const [watchlistId, setWatchlistId] = useState<number | "">("");
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const alerts = useQuery({
    queryKey: ["alerts", status, watchlistId],
    queryFn: () => api.alerts({ status: status || undefined, watchlist_id: watchlistId || undefined }),
    refetchInterval: 15_000,
  });
  const keys = useMemo(() => (alerts.data ?? []).map((a) => a.instrument.instrument_key), [alerts.data]);
  const prices = usePrices(keys);
  const columns = useMemo<SortColumns<AlertWithContext, AlertSortKey>>(
    () => ({
      watchlist: { value: (a) => a.watchlist_name },
      symbol: { value: (a) => a.instrument.trading_symbol },
      target: { value: (a) => a.target_price, first: "desc" },
      ltp: { value: (a) => prices.get(a.instrument.instrument_key)?.p, first: "desc" },
      // Closest to its target first; only watching alerts have a meaningful distance.
      to_target: {
        value: (a) => (a.status === "ACTIVE" ? Math.abs(distancePct(prices.get(a.instrument.instrument_key)?.p, a.target_price) ?? NaN) : null),
      },
      status: { value: (a) => STATUS_ORDER[a.status] },
      last_hit: { value: (a) => (a.last_triggered_at ? Date.parse(a.last_triggered_at) : null), first: "desc" },
    }),
    [prices],
  );
  const alertSort = useSort("alerts", columns);
  const rows = useMemo(() => sortRows(alerts.data ?? [], alertSort.sort, columns), [alerts.data, alertSort.sort, columns]);
  const header = (label: string, key: AlertSortKey, align?: "right", title?: string) => (
    <SortHeader label={label} sortKey={key} sort={alertSort.sort} onToggle={alertSort.toggle} align={align} title={title} />
  );

  const refresh = () =>
    Promise.all(["alerts", "items", "watchlists", "status"].map((k) => qc.invalidateQueries({ queryKey: [k] })));
  const act = useMutation({
    mutationFn: async ({ a, action }: { a: AlertWithContext; action: "rearm" | "disable" | "delete" }) => {
      if (action === "rearm") await api.rearmAlert(a.id);
      else if (action === "disable") await api.disableAlert(a.id);
      else await api.deleteAlert(a.id);
    },
    onSuccess: refresh,
  });

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 items-end gap-3 sm:flex sm:flex-wrap">
        <h1 className="col-span-2 text-xl font-semibold sm:mr-auto">All alerts</h1>
        <select className="input sm:w-44" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as AlertStatus | "")}>
          <option value="">All statuses</option>
          <option value="ACTIVE">Watching</option>
          <option value="TRIGGERED">Target hit</option>
          <option value="DISABLED">Disabled</option>
        </select>
        <select className="input sm:w-56" aria-label="Watchlist" value={watchlistId} onChange={(e) => setWatchlistId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">All watchlists</option>
          {lists.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </div>
      <ErrorText error={act.error} />

      <div className="card overflow-hidden">
        {alerts.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !alerts.data?.length ? (
          <div className="p-4">
            <EmptyState title="No alerts match">
              Add alerts from a <Link className="text-teal-700 underline" to="/watchlists">watchlist</Link>.
            </EmptyState>
          </div>
        ) : (
          <>
          {/* Phones: one card per alert, every action visible. */}
          <SortSelect className="border-b border-slate-200 p-3 md:hidden dark:border-slate-800" options={SORT_OPTIONS} sort={alertSort.sort} onChange={alertSort.set} />
          <ul className="divide-y divide-slate-100 md:hidden dark:divide-slate-800">
            {rows.map((a) => {
              const p = prices.get(a.instrument.instrument_key)?.p;
              return (
                <li key={a.id} className="space-y-2 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div>
                        <span className="font-medium">{a.instrument.trading_symbol}</span>
                        <span className="ml-1 text-xs text-slate-500">{exchangeOf(a.instrument.instrument_key)}</span>
                      </div>
                      <Link className="block truncate text-xs text-slate-500 hover:underline" to={`/watchlists/${a.watchlist_id}`}>
                        {a.watchlist_name}
                      </Link>
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-sm">
                    <div>
                      <div className="text-xs text-slate-500">Target</div>
                      <TargetText a={a} />
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-slate-500">LTP</div>
                      <PriceCell value={p} />
                    </div>
                    <div className="num text-right text-slate-600 dark:text-slate-300">
                      <div className="text-xs text-slate-500">To target</div>
                      {a.status === "ACTIVE" ? formatPct(distancePct(p, a.target_price)) : "—"}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-slate-500">
                      {a.last_triggered_at ? `Last hit ${formatIST(a.last_triggered_at)} at ${formatINR(a.last_trigger_price)}` : "Not hit yet"}
                    </span>
                    <Actions a={a} onAct={(action) => act.mutate({ a, action })} />
                  </div>
                </li>
              );
            })}
          </ul>
          <table className="hidden w-full md:table">
            <thead className="border-b border-slate-200 dark:border-slate-800">
              <tr>
                {header("Watchlist", "watchlist")}
                {header("Stock", "symbol")}
                {header("Target", "target", "right")}
                {header("LTP", "ltp", "right")}
                {header("To target", "to_target", "right", "Move needed from current price to reach the target")}
                {header("Status", "status")}
                {header("Last hit", "last_hit")}
                <th className="th sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {rows.map((a) => {
                const p = prices.get(a.instrument.instrument_key)?.p;
                const dist = distancePct(p, a.target_price);
                return (
                  <tr key={a.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                    <td className="td">
                      <Link className="hover:underline" to={`/watchlists/${a.watchlist_id}`}>
                        {a.watchlist_name}
                      </Link>
                    </td>
                    <td className="td">
                      <span className="font-medium">{a.instrument.trading_symbol}</span>
                      <span className="ml-1 text-xs text-slate-500">{exchangeOf(a.instrument.instrument_key)}</span>
                    </td>
                    <td className="td text-right">
                      <TargetText a={a} />
                    </td>
                    <td className="td text-right">
                      <PriceCell value={p} />
                    </td>
                    <td className="td num text-right text-sm text-slate-600 dark:text-slate-300">
                      {a.status === "ACTIVE" ? formatPct(dist) : "—"}
                    </td>
                    <td className="td">
                      <StatusBadge status={a.status} />
                    </td>
                    <td className="td text-xs text-slate-500">
                      {a.last_triggered_at ? (
                        <>
                          {formatIST(a.last_triggered_at)}
                          <br />
                          at {formatINR(a.last_trigger_price)}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="td whitespace-nowrap text-right">
                      <Actions a={a} onAct={(action) => act.mutate({ a, action })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </>
        )}
      </div>
    </section>
  );
}

function TargetText({ a }: { a: AlertWithContext }) {
  return (
    <span className="num">
      {conditionSymbol(a.condition)} {formatINR(a.target_price)}
      {a.check_from ? (
        <span className="block text-xs text-slate-500" title="Checked every trading day in this window (IST)">
          {formatWindow(a.check_from, a.check_until)}
        </span>
      ) : (
        a.trigger_mode === "REPEAT" && <span className="ml-1 text-xs text-slate-500" title="Re-arms automatically">↻</span>
      )}
    </span>
  );
}

function Actions({ a, onAct }: { a: AlertWithContext; onAct: (action: "rearm" | "disable" | "delete") => void }) {
  const confirm = useConfirm();
  const askDelete = async () => {
    const ok = await confirm({
      title: "Delete this alert?",
      message: `${a.instrument.trading_symbol} ${conditionSymbol(a.condition)} ${formatINR(a.target_price)} · ${a.watchlist_name}. Its history is kept.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (ok) onAct("delete");
  };
  return (
    <span className="inline-flex gap-2">
      {a.status === "ACTIVE" ? (
        <button className="btn btn-sm" onClick={() => onAct("disable")}>
          Disable
        </button>
      ) : (
        <button className="btn btn-sm" onClick={() => onAct("rearm")}>
          Re-arm
        </button>
      )}
      <button className="btn btn-sm btn-danger" onClick={askDelete}>
        Delete
      </button>
    </span>
  );
}
