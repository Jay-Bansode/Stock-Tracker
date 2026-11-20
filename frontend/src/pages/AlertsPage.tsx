import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { conditionSymbol, EmptyState, ErrorText, PriceCell, StatusBadge } from "../components/ui";
import { distancePct, exchangeOf, formatINR, formatIST, formatPct, formatWindow } from "../format";
import { usePrices } from "../prices";
import type { AlertStatus, AlertWithContext } from "../types";

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
          <ul className="divide-y divide-slate-100 md:hidden dark:divide-slate-800">
            {alerts.data.map((a) => {
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
                <th className="th">Watchlist</th>
                <th className="th">Stock</th>
                <th className="th text-right">Target</th>
                <th className="th text-right">LTP</th>
                <th className="th text-right" title="Move needed from current price to reach the target">To target</th>
                <th className="th">Status</th>
                <th className="th">Last hit</th>
                <th className="th sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {alerts.data.map((a) => {
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
      <button className="btn btn-sm btn-danger" onClick={() => confirm("Delete this alert? Its history is kept.") && onAct("delete")}>
        Delete
      </button>
    </span>
  );
}
