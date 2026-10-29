import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { conditionSymbol, EmptyState, ErrorText, PriceCell, StatusBadge } from "../components/ui";
import { distancePct, exchangeOf, formatINR, formatIST, formatPct } from "../format";
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
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-xl font-semibold">All alerts</h1>
        <select className="input w-44" value={status} onChange={(e) => setStatus(e.target.value as AlertStatus | "")}>
          <option value="">All statuses</option>
          <option value="ACTIVE">Watching</option>
          <option value="TRIGGERED">Target hit</option>
          <option value="DISABLED">Disabled</option>
        </select>
        <select className="input w-56" value={watchlistId} onChange={(e) => setWatchlistId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">All watchlists</option>
          {lists.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </div>
      <ErrorText error={act.error} />

      <div className="card overflow-x-auto">
        {alerts.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !alerts.data?.length ? (
          <div className="p-4">
            <EmptyState title="No alerts match">
              Add alerts from a <Link className="text-teal-700 underline" to="/watchlists">watchlist</Link>.
            </EmptyState>
          </div>
        ) : (
          <table className="w-full">
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
                    <td className="td num text-right">
                      {conditionSymbol(a.condition)} {formatINR(a.target_price)}
                      {a.trigger_mode === "REPEAT" && <span className="ml-1 text-xs text-slate-500" title="Re-arms automatically">↻</span>}
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
                      {a.status === "ACTIVE" ? (
                        <button className="btn btn-sm" onClick={() => act.mutate({ a, action: "disable" })}>
                          Disable
                        </button>
                      ) : (
                        <button className="btn btn-sm" onClick={() => act.mutate({ a, action: "rearm" })}>
                          Re-arm
                        </button>
                      )}{" "}
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => confirm("Delete this alert? Its history is kept.") && act.mutate({ a, action: "delete" })}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
