import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { ErrorText } from "../components/ui";
import { formatIST, timeAgo } from "../format";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={`mr-1.5 inline-block size-2 rounded-full ${ok ? "bg-emerald-500" : warn ? "bg-amber-500" : "bg-red-500"}`} />;
}

export default function SettingsPage() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 5_000 });
  const s = status.data;
  const engine = s?.engine;
  const engineAlive = !!engine && engine.heartbeat_age_sec < 30;

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Settings &amp; status</h1>
      <ErrorText error={status.error} />
      {s && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
            <h2 className="pb-2 font-semibold">Market data</h2>
            {s.mode === "cron" ? (
              <>
                <Row label="Mode">Free hosting: checked once a minute by your scheduler</Row>
                <Row label="Provider">{s.provider === "upstox" ? "Upstox REST (price + 1-min high/low)" : "Simulated prices"}</Row>
                {s.poll ? (
                  <>
                    <Row label="Last check">
                      <Dot ok={s.poll.ok} />
                      {timeAgo(Date.parse(s.poll.at) / 1000)} ({formatIST(s.poll.at)})
                    </Row>
                    {s.poll.error && <Row label="Last error"><span className="text-red-600">{s.poll.error}</span></Row>}
                    <Row label="Market open at last check">{s.poll.market_open ? "Yes" : "No"}</Row>
                    <Row label="Stocks checked">{s.poll.polled}</Row>
                    <Row label="Alert rules checked">{s.poll.rules}</Row>
                    <Row label="Fired / messages sent">
                      {s.poll.events} / {s.poll.sent}
                    </Row>
                  </>
                ) : (
                  <Row label="Last check">
                    <Dot ok={false} warn />
                    None yet. Set up the cron job for /api/cron/poll.
                  </Row>
                )}
              </>
            ) : (
              <>
                <Row label="Provider">{s.provider === "upstox" ? "Upstox V3 live feed" : "Simulated prices"}</Row>
                <Row label="Engine">
                  <Dot ok={engineAlive} />
                  {engineAlive ? "Running" : "Offline. Check the engine container logs."}
                </Row>
              </>
            )}
            {engine && (
              <>
                <Row label="Feed">
                  <Dot ok={engine.connected} warn={!engine.market_window_open} />
                  {engine.connected ? "Connected" : engine.market_window_open ? "Reconnecting…" : "Idle (outside market hours)"}
                </Row>
                <Row label="Segments">
                  {Object.entries(engine.market_status).length
                    ? Object.entries(engine.market_status).map(([seg, st]) => (
                        <span key={seg} className="block text-xs">
                          {seg}: {st.replaceAll("_", " ").toLowerCase()}
                        </span>
                      ))
                    : "—"}
                </Row>
                <Row label="Streaming instruments">{engine.subscriptions}</Row>
                <Row label="Alert rules in memory">{engine.active_rules}</Row>
                <Row label="Last tick">{engine.last_tick_at ? `${timeAgo(engine.last_tick_at)} (${formatIST(engine.last_tick_at * 1000)})` : "none yet"}</Row>
              </>
            )}
            {s.provider === "upstox" && (
              <>
                <Row label="Analytics token">
                  <Dot ok={s.upstox_token_set} />
                  {s.upstox_token_set ? "Configured" : "Missing: set UPSTOX_ANALYTICS_TOKEN"}
                </Row>
                {s.upstox_token_expires_on && (
                  <Row label="Token expires">
                    <Dot ok={(s.upstox_token_days_left ?? 0) > 7} warn={(s.upstox_token_days_left ?? 0) > 0} />
                    {s.upstox_token_expires_on} ({s.upstox_token_days_left} days)
                  </Row>
                )}
              </>
            )}
          </div>

          <div className="space-y-4">
            <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
              <h2 className="pb-2 font-semibold">Notifications</h2>
              <ChannelRow channel="TELEGRAM" label="Telegram" configured={s.channels.TELEGRAM} hint="TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID" />
              <ChannelRow channel="WHATSAPP" label="WhatsApp" configured={s.channels.WHATSAPP} hint="WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TO" />
            </div>
            <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
              <h2 className="pb-2 font-semibold">Alerts</h2>
              <Row label="Watching">{s.alerts.active}</Row>
              <Row label="Target hit (awaiting re-arm)">{s.alerts.triggered}</Row>
              <Row label="Fired today">{s.alerts.fired_today}</Row>
            </div>
            {s.provider === "simulated" && <DevTicks />}
          </div>
        </div>
      )}
    </section>
  );
}

function ChannelRow({ channel, label, configured, hint }: { channel: string; label: string; configured: boolean; hint: string }) {
  const test = useMutation({ mutationFn: () => api.testNotification(channel) });
  return (
    <div className="py-2 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span>
          <Dot ok={configured} />
          <span className="font-medium">{label}</span>{" "}
          <span className="text-slate-500">{configured ? "configured" : `not configured: set ${hint}`}</span>
        </span>
        <button className="btn btn-sm" disabled={!configured || test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Sending…" : "Send test"}
        </button>
      </div>
      {test.isSuccess && <p className="mt-1 text-xs text-emerald-700 dark:text-emerald-400">Sent. Check {label}.</p>}
      {test.error && <p className="mt-1 text-xs break-words text-red-600">{test.error.message}</p>}
    </div>
  );
}

function DevTicks() {
  const [symbol, setSymbol] = useState("RELIANCE");
  const [price, setPrice] = useState("1502");
  const inject = useMutation({ mutationFn: () => api.injectTicks({ [symbol.trim()]: Number(price) }) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    inject.mutate();
  };
  return (
    <form onSubmit={submit} className="card space-y-3 p-4">
      <div>
        <h2 className="font-semibold">Simulator: set a price</h2>
        <p className="text-xs text-slate-500">Pushes an exact tick through the alert engine, the same path live Upstox ticks take.</p>
      </div>
      <div className="flex gap-2">
        <input className="input w-36" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Symbol" />
        <input className="input num w-28" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Price" />
        <button className="btn btn-primary whitespace-nowrap" disabled={inject.isPending || !symbol || !Number(price)}>
          Push tick
        </button>
      </div>
      {inject.isSuccess && <p className="text-xs text-emerald-700 dark:text-emerald-400">Published {inject.data.published.map((p) => `${p.k} @ ${p.p}`).join(", ")}
          {inject.data.events !== undefined && ` · ${inject.data.events} alert(s) fired, ${inject.data.sent} message(s) sent`}</p>}
      <ErrorText error={inject.error} />
    </form>
  );
}
