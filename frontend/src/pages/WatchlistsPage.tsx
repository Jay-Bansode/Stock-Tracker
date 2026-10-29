import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { api } from "../api";
import { AlertForm } from "../components/AlertForm";
import { InstrumentSearch } from "../components/InstrumentSearch";
import { AlertChip, ChangeText, EmptyState, ErrorText, PriceCell, StatusBadge } from "../components/ui";
import { dayChangePct, exchangeOf, formatIST, formatINR } from "../format";
import { usePrices } from "../prices";
import type { Alert, AlertInput, Price, Watchlist, WatchlistItem } from "../types";

function useInvalidate() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["items"] }),
      qc.invalidateQueries({ queryKey: ["watchlists"] }),
      qc.invalidateQueries({ queryKey: ["alerts"] }),
      qc.invalidateQueries({ queryKey: ["status"] }),
    ]);
}

export default function WatchlistsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const selectedId = id ? Number(id) : undefined;
  const selected = lists.data?.find((w) => w.id === selectedId);

  useEffect(() => {
    if (lists.data?.length && !selected) navigate(`/watchlists/${lists.data[0].id}`, { replace: true });
  }, [lists.data, selected, navigate]);

  return (
    <div className="grid gap-6 md:grid-cols-[260px_minmax(0,1fr)]">
      <Sidebar lists={lists.data ?? []} selectedId={selectedId} />
      {lists.isPending ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : selected ? (
        <WatchlistDetail key={selected.id} watchlist={selected} />
      ) : (
        <EmptyState title="No watchlists yet">Create one on the left, e.g. “Long-Term Stocks”.</EmptyState>
      )}
    </div>
  );
}

function Sidebar({ lists, selectedId }: { lists: Watchlist[]; selectedId?: number }) {
  const navigate = useNavigate();
  const invalidate = useInvalidate();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.createWatchlist(name.trim()),
    onSuccess: async (wl) => {
      setName("");
      await invalidate();
      navigate(`/watchlists/${wl.id}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <aside className="space-y-3">
      <h2 className="px-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">Watchlists</h2>
      <ul className="space-y-1">
        {lists.map((w) => (
          <li key={w.id}>
            <button
              onClick={() => navigate(`/watchlists/${w.id}`)}
              className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                w.id === selectedId
                  ? "bg-white font-medium shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800"
                  : "hover:bg-slate-100 dark:hover:bg-slate-900"
              }`}
            >
              <span className="truncate">{w.name}</span>
              <span className="flex shrink-0 items-center gap-1.5 text-xs text-slate-500">
                {w.triggered_alerts > 0 && (
                  <span className="rounded bg-amber-100 px-1.5 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300" title="Alerts with target hit">
                    {w.triggered_alerts} hit
                  </span>
                )}
                <span title="Stocks">{w.item_count}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="flex gap-2">
        <input className="input" placeholder="New watchlist" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <button className="btn btn-primary" disabled={!name.trim() || create.isPending}>
          Add
        </button>
      </form>
      <ErrorText error={create.error} />
    </aside>
  );
}

function WatchlistDetail({ watchlist }: { watchlist: Watchlist }) {
  const navigate = useNavigate();
  const invalidate = useInvalidate();
  const items = useQuery({ queryKey: ["items", watchlist.id], queryFn: () => api.items(watchlist.id) });
  const keys = useMemo(() => (items.data ?? []).map((i) => i.instrument.instrument_key), [items.data]);
  const prices = usePrices(keys);
  const existing = useMemo(() => new Set(keys), [keys]);

  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(watchlist.name);
  const rename = useMutation({
    mutationFn: () => api.updateWatchlist(watchlist.id, { name: newName.trim() }),
    onSuccess: async () => {
      setRenaming(false);
      await invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteWatchlist(watchlist.id),
    onSuccess: async () => {
      await invalidate();
      navigate("/watchlists", { replace: true });
    },
  });
  const addItem = useMutation({
    mutationFn: (key: string) => api.addItem(watchlist.id, key),
    onSuccess: invalidate,
  });

  return (
    <section className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        {renaming ? (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (newName.trim()) rename.mutate();
            }}
          >
            <input className="input w-64" autoFocus value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} />
            <button className="btn btn-primary">Save</button>
            <button type="button" className="btn" onClick={() => setRenaming(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <h1 className="text-xl font-semibold">{watchlist.name}</h1>
        )}
        <span className="text-sm text-slate-500">
          {watchlist.item_count} {watchlist.item_count === 1 ? "stock" : "stocks"} · {watchlist.active_alerts} watching · {watchlist.triggered_alerts} hit
        </span>
        <div className="ml-auto flex gap-2">
          {!renaming && (
            <button className="btn btn-sm" onClick={() => setRenaming(true)}>
              Rename
            </button>
          )}
          <button
            className="btn btn-sm btn-danger"
            onClick={() => {
              if (confirm(`Delete “${watchlist.name}” and all its alerts? Alert history is kept.`)) remove.mutate();
            }}
          >
            Delete
          </button>
        </div>
      </div>
      <ErrorText error={rename.error ?? remove.error} />

      <div className="flex flex-wrap items-center gap-3">
        <InstrumentSearch existing={existing} disabled={addItem.isPending} onSelect={(i) => addItem.mutate(i.instrument_key)} />
        <ErrorText error={addItem.error} />
      </div>

      <div className="card overflow-x-auto">
        {items.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !items.data?.length ? (
          <div className="p-4">
            <EmptyState title="No stocks in this watchlist">Search above to add one, then set a target price.</EmptyState>
          </div>
        ) : (
          <table className="w-full">
            <thead className="border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="th">Stock</th>
                <th className="th text-right">LTP</th>
                <th className="th text-right">Day</th>
                <th className="th">Alerts</th>
                <th className="th sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.data.map((item) => (
                <ItemRow key={item.id} item={item} price={prices.get(item.instrument.instrument_key)} onChanged={invalidate} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function ItemRow({ item, price, onChanged }: { item: WatchlistItem; price?: Price; onChanged: () => Promise<unknown> }) {
  const [editing, setEditing] = useState<"new" | number | null>(null);
  const editingAlert: Alert | undefined = typeof editing === "number" ? item.alerts.find((a) => a.id === editing) : undefined;

  const done = async () => {
    setEditing(null);
    await onChanged();
  };
  const save = useMutation({
    mutationFn: (input: AlertInput) =>
      editingAlert ? api.updateAlert(editingAlert.id, input) : api.createAlert(item.id, input),
    onSuccess: done,
  });
  const del = useMutation({ mutationFn: (id: number) => api.deleteAlert(id), onSuccess: done });
  const toggle = useMutation({
    mutationFn: (a: Alert) => (a.status === "ACTIVE" ? api.disableAlert(a.id) : api.rearmAlert(a.id)),
    onSuccess: onChanged,
  });
  const removeItem = useMutation({ mutationFn: () => api.removeItem(item.watchlist_id, item.id), onSuccess: onChanged });

  const i = item.instrument;
  return (
    <Fragment>
      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
        <td className="td">
          <div className="font-medium">{i.trading_symbol}</div>
          <div className="max-w-64 truncate text-xs text-slate-500">
            {i.name} · {exchangeOf(i.instrument_key)}
          </div>
        </td>
        <td className="td text-right">
          <PriceCell value={price?.p} />
        </td>
        <td className="td text-right text-sm">
          <ChangeText pct={dayChangePct(price?.p, price?.c)} />
        </td>
        <td className="td">
          <div className="flex flex-wrap items-center gap-1.5">
            {item.alerts.map((a) => (
              <AlertChip key={a.id} condition={a.condition} target={a.target_price} status={a.status} onClick={() => setEditing(a.id)} />
            ))}
            <button className="btn btn-sm" onClick={() => setEditing("new")}>
              + Alert
            </button>
          </div>
        </td>
        <td className="td text-right">
          <button
            className="btn btn-sm btn-danger"
            title="Remove from watchlist"
            onClick={() => {
              if (!item.alerts.length || confirm(`Remove ${i.trading_symbol} and its ${item.alerts.length} alert(s) from this watchlist?`))
                removeItem.mutate();
            }}
          >
            Remove
          </button>
        </td>
      </tr>
      {editing !== null && (
        <tr>
          <td colSpan={5} className="px-3 pb-3">
            {editingAlert && (
              <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                <StatusBadge status={editingAlert.status} />
                {editingAlert.last_triggered_at && (
                  <span>
                    Last hit {formatIST(editingAlert.last_triggered_at)} at {formatINR(editingAlert.last_trigger_price)} · fired{" "}
                    {editingAlert.trigger_count}×
                  </span>
                )}
                <button className="btn btn-sm" disabled={toggle.isPending} onClick={() => toggle.mutate(editingAlert)}>
                  {editingAlert.status === "ACTIVE" ? "Disable" : "Re-arm"}
                </button>
              </div>
            )}
            <AlertForm
              key={editing}
              initial={editingAlert}
              ltp={price?.p}
              busy={save.isPending || del.isPending}
              error={save.error ?? del.error ?? toggle.error}
              onSubmit={(input) => save.mutate(input)}
              onCancel={() => setEditing(null)}
              onDelete={editingAlert ? () => del.mutate(editingAlert.id) : undefined}
            />
          </td>
        </tr>
      )}
    </Fragment>
  );
}
