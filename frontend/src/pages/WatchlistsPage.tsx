import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { api } from "../api";
import { AlertForm } from "../components/AlertForm";
import { useConfirm } from "../components/ConfirmDialog";
import { InstrumentSearch } from "../components/InstrumentSearch";
import { AlertChip, ChangeText, EmptyState, ErrorText, PriceCell, StatusBadge } from "../components/ui";
import { dayChangePct, exchangeOf, formatDate, formatIST, formatINR, formatWindow, heldFor, todayIST } from "../format";
import { usePrices } from "../prices";
import type { Alert, AlertInput, Price, Watchlist, WatchlistItem } from "../types";

// Desktop columns: Stock | LTP | Day | Held | Alerts | Remove. Shared by the header and every row.
// The header and each row are separate grids, so every track must be fixed or fr: a content-sized
// ("auto") track would be 0 px in the header but button-wide in rows, shifting the columns.
const ROW_GRID_MD = "md:grid-cols-[minmax(0,1.3fr)_6.5rem_4.5rem_5.5rem_minmax(0,2fr)_5rem] md:gap-x-3 md:px-3";
const ROW_GRID = `grid ${ROW_GRID_MD}`;

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
    <div className="grid gap-4 md:grid-cols-[240px_minmax(0,1fr)] md:gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
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
    <aside className="min-w-0 space-y-3">
      <h2 className="hidden px-1 text-xs font-semibold tracking-wide text-slate-500 uppercase md:block">Watchlists</h2>
      {/* Phones: a swipeable row of pills. md+: a vertical list. */}
      <ul className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:block md:space-y-1 md:overflow-visible md:px-0 md:pb-0">
        {lists.map((w) => {
          const active = w.id === selectedId;
          return (
            <li key={w.id} className="shrink-0">
              <button
                onClick={() => navigate(`/watchlists/${w.id}`)}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-left text-sm whitespace-nowrap md:w-full md:justify-between md:rounded-lg md:border-0 md:py-2 md:whitespace-normal ${
                  active
                    ? "border-teal-600 bg-teal-50 font-medium text-teal-900 md:bg-white md:text-inherit md:shadow-sm md:ring-1 md:ring-slate-200 dark:bg-teal-950 dark:text-teal-100 md:dark:bg-slate-900 md:dark:ring-slate-800"
                    : "border-slate-200 bg-white hover:bg-slate-100 md:bg-transparent dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-900 md:dark:bg-transparent"
                }`}
              >
                <span className="max-w-48 truncate md:max-w-none">{w.name}</span>
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
          );
        })}
      </ul>
      <form onSubmit={submit} className="flex gap-2">
        <input className="input min-w-0" placeholder="New watchlist" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        <button className="btn btn-primary shrink-0" disabled={!name.trim() || create.isPending}>
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
  const confirm = useConfirm();
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {renaming ? (
          <form
            className="flex w-full gap-2 sm:w-auto"
            onSubmit={(e) => {
              e.preventDefault();
              if (newName.trim()) rename.mutate();
            }}
          >
            <input className="input min-w-0 sm:w-64" autoFocus value={newName} maxLength={100} onChange={(e) => setNewName(e.target.value)} />
            <button className="btn btn-primary">Save</button>
            <button type="button" className="btn" onClick={() => setRenaming(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <h1 className="min-w-0 text-xl font-semibold break-words">{watchlist.name}</h1>
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
            onClick={async () => {
              const ok = await confirm({
                title: `Delete “${watchlist.name}”?`,
                message: "All its stocks and alerts are removed. Alert history is kept.",
                confirmLabel: "Delete",
                danger: true,
              });
              if (ok) remove.mutate();
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

      <div className="card">
        {items.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !items.data?.length ? (
          <div className="p-4">
            <EmptyState title="No stocks in this watchlist">Search above to add one, then set a target price.</EmptyState>
          </div>
        ) : (
          <>
            <div className={`${ROW_GRID} hidden border-b border-slate-200 md:grid dark:border-slate-800`}>
              <span className="th px-0">Stock</span>
              <span className="th px-0 text-right">LTP</span>
              <span className="th px-0 text-right">Day</span>
              <span className="th px-0" title="How long you've held it, from the buying date">
                Held
              </span>
              <span className="th px-0">Alerts</span>
              <span className="sr-only">Actions</span>
            </div>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.data.map((item) => (
                <ItemRow key={item.id} item={item} watchlistName={watchlist.name} price={prices.get(item.instrument.instrument_key)} onChanged={invalidate} />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

function ItemRow({
  item,
  watchlistName,
  price,
  onChanged,
}: {
  item: WatchlistItem;
  watchlistName: string;
  price?: Price;
  onChanged: () => Promise<unknown>;
}) {
  const confirm = useConfirm();
  // What's open under the row: a new alert, an existing alert (its id), or the buying date.
  const [editing, setEditing] = useState<"new" | number | "date" | null>(null);
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
    <li className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
      {/* Phones: a two-column card (stock | price, then alerts + remove). md+: one grid row whose
          cells line up with the header; the md:contents wrappers dissolve so their children
          become the LTP / Day / Alerts / Remove columns. */}
      <div className={`grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 px-3 py-3 ${ROW_GRID_MD} md:items-center md:py-0`}>
        <div className="min-w-0 md:py-2.5">
          <div className="font-medium">{i.trading_symbol}</div>
          <div className="truncate text-xs text-slate-500">
            {i.name} · {exchangeOf(i.instrument_key)}
          </div>
          <div className="mt-0.5 text-xs md:hidden">
            <HeldButton boughtOn={item.bought_on} onClick={() => setEditing("date")} withLabel />
          </div>
        </div>
        <div className="flex flex-col items-end text-sm md:contents">
          <div className="md:text-right">
            <PriceCell value={price?.p} />
          </div>
          <div className="text-xs md:text-right md:text-sm">
            <ChangeText pct={dayChangePct(price?.p, price?.c)} />
          </div>
        </div>
        <div className="hidden text-sm md:block">
          <HeldButton boughtOn={item.bought_on} onClick={() => setEditing("date")} />
        </div>
        <div className="col-span-2 flex items-start justify-between gap-2 md:contents">
          <div className="flex min-w-0 flex-wrap items-center gap-1.5 md:py-2.5">
            {item.alerts.map((a) => (
              <AlertChip key={a.id} condition={a.condition} target={a.target_price} status={a.status} when={formatWindow(a.check_from, a.check_until)} onClick={() => setEditing(a.id)} />
            ))}
            <button className="btn btn-sm" onClick={() => setEditing("new")}>
              + Alert
            </button>
          </div>
          <div className="shrink-0 md:text-right">
            <button
              className="btn btn-sm btn-danger"
              title="Remove from watchlist"
              onClick={async () => {
                const n = item.alerts.length;
                const ok = await confirm({
                  title: `Remove ${i.trading_symbol}?`,
                  message: n
                    ? `Its ${n === 1 ? "alert is" : `${n} alerts are`} removed too. Alert history is kept.`
                    : `It's removed from “${watchlistName}”. You can add it again any time.`,
                  confirmLabel: "Remove",
                  danger: true,
                });
                if (ok) removeItem.mutate();
              }}
            >
              Remove
            </button>
          </div>
        </div>
      </div>
      {editing === "date" && (
        <div className="px-3 pb-3">
          <BuyDateEditor item={item} onDone={() => setEditing(null)} onChanged={onChanged} />
        </div>
      )}
      {editing !== null && editing !== "date" && (
        <div className="px-3 pb-3">
          {editingAlert && (
            <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-slate-500">
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
            onDelete={
              editingAlert
                ? async () => {
                    const ok = await confirm({ title: "Delete this alert?", message: "Its history is kept.", confirmLabel: "Delete", danger: true });
                    if (ok) del.mutate(editingAlert.id);
                  }
                : undefined
            }
          />
        </div>
      )}
    </li>
  );
}

/** "2y 3m" (tooltip: the buying date), or "+ Buy date" when none is set. */
function HeldButton({ boughtOn, onClick, withLabel = false }: { boughtOn: string | null; onClick: () => void; withLabel?: boolean }) {
  const held = heldFor(boughtOn);
  if (!boughtOn) {
    return (
      <button className="text-xs font-medium text-teal-700 hover:underline dark:text-teal-400" onClick={onClick}>
        + Buy date
      </button>
    );
  }
  return (
    <button className="num text-left hover:underline" title={`Bought ${formatDate(boughtOn)} · click to change`} onClick={onClick}>
      {withLabel && <span className="text-slate-500">Held </span>}
      <span className="font-medium text-slate-700 dark:text-slate-200">{held || "—"}</span>
    </button>
  );
}

function BuyDateEditor({ item, onDone, onChanged }: { item: WatchlistItem; onDone: () => void; onChanged: () => Promise<unknown> }) {
  const today = todayIST();
  const [value, setValue] = useState(item.bought_on ?? "");
  const save = useMutation({
    mutationFn: (bought_on: string | null) => api.updateItem(item.watchlist_id, item.id, { bought_on }),
    onSuccess: async () => {
      onDone();
      await onChanged();
    },
  });
  const valid = !!value && value <= today;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) save.mutate(value);
  };

  return (
    <form
      onSubmit={submit}
      onKeyDown={(e) => e.key === "Escape" && onDone()}
      className="flex flex-wrap items-end gap-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50"
    >
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-slate-500">Buying date of {item.instrument.trading_symbol}</span>
        <input className="input num sm:w-44" type="date" autoFocus max={today} min="1990-01-01" required value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      {valid && <span className="pb-2 text-xs text-slate-500">Held {heldFor(value, today)}</span>}
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-primary" disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        {item.bought_on && (
          <button type="button" className="btn btn-danger" disabled={save.isPending} onClick={() => save.mutate(null)}>
            Clear
          </button>
        )}
      </div>
      {save.error && <ErrorText error={save.error} />}
    </form>
  );
}
