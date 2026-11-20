import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type HistoryFilters } from "../api";
import { conditionSymbol, DeliveryStatus, EmptyState, ErrorText } from "../components/ui";
import { exchangeOf, formatINR, formatIST } from "../format";

const PAGE_SIZE = 50;

export default function HistoryPage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<HistoryFilters>({});
  const [page, setPage] = useState(1);
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const query = { ...filters, page, page_size: PAGE_SIZE };
  const history = useQuery({
    queryKey: ["history", query],
    queryFn: () => api.history(query),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
  const retry = useMutation({
    mutationFn: api.retryNotification,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });

  const set = (patch: HistoryFilters) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };
  const totalPages = Math.max(1, Math.ceil((history.data?.total ?? 0) / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 items-end gap-3 sm:flex sm:flex-wrap">
        <div className="col-span-2 sm:mr-auto">
          <h1 className="text-xl font-semibold">Alert history</h1>
          <p className="text-sm text-slate-500">Every target hit, per watchlist, with delivery status for each channel.</p>
        </div>
        <select
          className="input col-span-2 sm:w-52"
          aria-label="Watchlist"
          value={filters.watchlist_id ?? ""}
          onChange={(e) => set({ watchlist_id: e.target.value ? Number(e.target.value) : undefined })}
        >
          <option value="">All watchlists</option>
          {lists.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <input className="input col-span-2 sm:w-36" aria-label="Symbol" placeholder="Symbol" value={filters.symbol ?? ""} onChange={(e) => set({ symbol: e.target.value || undefined })} />
        <label className="flex flex-col gap-1 text-xs text-slate-500 sm:flex-row sm:items-center sm:gap-1.5">
          From
          <input type="date" className="input sm:w-40" value={filters.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || undefined })} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500 sm:flex-row sm:items-center sm:gap-1.5">
          To
          <input type="date" className="input sm:w-40" value={filters.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || undefined })} />
        </label>
        <a className="btn col-span-2" href={api.historyCsvUrl(filters)}>
          Export CSV
        </a>
      </div>
      <ErrorText error={retry.error} />

      <div className="card overflow-hidden">
        {history.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !history.data?.items.length ? (
          <div className="p-4">
            <EmptyState title="No alerts have fired yet">When a target is hit it will appear here.</EmptyState>
          </div>
        ) : (
          <>
          {/* Phones: one card per event. */}
          <ul className="divide-y divide-slate-100 md:hidden dark:divide-slate-800">
            {history.data.items.map((e) => {
              const byChannel = Object.fromEntries(e.notifications.map((n) => [n.channel, n]));
              return (
                <li key={e.id} className="space-y-2 p-3 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium">
                        {e.trading_symbol} <span className="text-xs font-normal text-slate-500">{exchangeOf(e.instrument_key)}</span>
                      </div>
                      <div className="truncate text-xs text-slate-500">{e.company_name}</div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="num font-medium">{formatINR(e.trigger_price)}</div>
                      <div className="num text-xs text-slate-500">
                        target {conditionSymbol(e.condition)} {formatINR(e.target_price)}
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span className="num">{formatIST(e.exchange_ts ?? e.triggered_at)}</span>
                    <span className="truncate">{e.watchlist_name}</span>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="text-slate-500">Telegram</span>
                      <DeliveryStatus row={byChannel.TELEGRAM} onRetry={(id) => retry.mutate(id)} />
                    </span>
                    {byChannel.WHATSAPP && (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="text-slate-500">WhatsApp</span>
                        <DeliveryStatus row={byChannel.WHATSAPP} onRetry={(id) => retry.mutate(id)} />
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
          <table className="hidden w-full md:table">
            <thead className="border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="th">Time</th>
                <th className="th">Watchlist</th>
                <th className="th">Stock</th>
                <th className="th text-right">Target</th>
                <th className="th text-right">Price at hit</th>
                <th className="th">Telegram</th>
                <th className="th">WhatsApp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {history.data.items.map((e) => {
                const byChannel = Object.fromEntries(e.notifications.map((n) => [n.channel, n]));
                return (
                  <tr key={e.id}>
                    <td className="td num whitespace-nowrap text-xs">{formatIST(e.exchange_ts ?? e.triggered_at)}</td>
                    <td className="td">{e.watchlist_name}</td>
                    <td className="td">
                      <div className="font-medium">
                        {e.trading_symbol} <span className="text-xs font-normal text-slate-500">{exchangeOf(e.instrument_key)}</span>
                      </div>
                      <div className="text-xs text-slate-500">{e.company_name}</div>
                    </td>
                    <td className="td num text-right">
                      {conditionSymbol(e.condition)} {formatINR(e.target_price)}
                    </td>
                    <td className="td num text-right font-medium">{formatINR(e.trigger_price)}</td>
                    <td className="td">
                      <DeliveryStatus row={byChannel.TELEGRAM} onRetry={(id) => retry.mutate(id)} />
                    </td>
                    <td className="td">
                      <DeliveryStatus row={byChannel.WHATSAPP} onRetry={(id) => retry.mutate(id)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </>
        )}
      </div>

      {history.data && history.data.total > PAGE_SIZE && (
        <div className="flex flex-wrap items-center justify-end gap-3 text-sm">
          <span className="w-full text-center text-slate-500 sm:w-auto">
            Page {page} of {totalPages} · {history.data.total} events
          </span>
          <button className="btn btn-sm flex-1 py-2 sm:flex-none sm:py-1" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <button className="btn btn-sm flex-1 py-2 sm:flex-none sm:py-1" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </button>
        </div>
      )}
    </section>
  );
}
