import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import { ErrorText } from "../components/ui";
import { formatIST, timeAgo } from "../format";
import { ME_KEY } from "../queryClient";
import type { Me } from "../types";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 font-medium break-words sm:text-right">{children}</span>
    </div>
  );
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={`mr-1.5 inline-block size-2 rounded-full ${ok ? "bg-emerald-500" : warn ? "bg-amber-500" : "bg-red-500"}`} />;
}

function useMe() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ME_KEY, queryFn: api.me, staleTime: Infinity }).data;
  const setMe = (m: Me) => {
    qc.setQueryData(ME_KEY, m);
    void qc.invalidateQueries({ queryKey: ["status"] });
  };
  return [me, setMe] as const;
}

export default function SettingsPage() {
  const [me] = useMe();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 5_000 });
  const s = status.data;
  const engine = s?.engine;
  const engineAlive = !!engine && engine.heartbeat_age_sec < 30;

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Settings &amp; status</h1>
      <ErrorText error={status.error} />
      {me && (
        <div className="grid gap-4 md:grid-cols-2">
          <AccountCard me={me} />
          <TelegramCard me={me} botConfigured={s?.telegram_bot ?? true} />
        </div>
      )}
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
            {me?.is_admin && (
              <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
                <h2 className="pb-2 font-semibold">WhatsApp (admin only)</h2>
                <ChannelRow channel="WHATSAPP" label="WhatsApp" configured={s.channels.WHATSAPP} hint="WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TO" />
              </div>
            )}
            <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
              <h2 className="pb-2 font-semibold">Alerts</h2>
              <Row label="Watching">{s.alerts.active}</Row>
              <Row label="Target hit (awaiting re-arm)">{s.alerts.triggered}</Row>
              <Row label="Fired today">{s.alerts.fired_today}</Row>
            </div>
            {s.provider === "simulated" && me?.is_admin && <DevTicks />}
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
      <div className="flex flex-wrap items-center justify-between gap-3">
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

function AccountCard({ me }: { me: Me }) {
  const [, setMe] = useMe();
  const [editing, setEditing] = useState<"" | "password" | "email">("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [email, setEmail] = useState(me.email);
  const close = () => {
    setEditing("");
    setCurrent("");
    setNext("");
  };
  const save = useMutation({
    mutationFn: () => (editing === "password" ? api.changePassword(current, next) : api.changeEmail(email.trim(), current)),
    onSuccess: (m) => {
      setMe(m);
      close();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const open = (what: "password" | "email") => {
    save.reset();
    setEmail(me.email);
    setEditing(what);
  };

  return (
    <div className="card divide-y divide-slate-100 p-4 dark:divide-slate-800">
      <h2 className="pb-2 font-semibold">Account</h2>
      <Row label="Username">
        {me.username}
        {me.is_admin && <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">admin</span>}
      </Row>
      <Row label="Email">{me.email}</Row>
      {editing ? (
        <form onSubmit={submit} className="space-y-2 pt-3">
          {editing === "email" ? (
            <input className="input" type="email" autoComplete="email" aria-label="New email" placeholder="New email" value={email} onChange={(e) => setEmail(e.target.value)} />
          ) : (
            <input className="input" type="password" autoComplete="new-password" aria-label="New password" placeholder="New password (8+ characters)" minLength={8} maxLength={72} value={next} onChange={(e) => setNext(e.target.value)} />
          )}
          <input className="input" type="password" autoComplete="current-password" aria-label="Current password" placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          <ErrorText error={save.error} />
          <div className="flex gap-2">
            <button className="btn btn-primary btn-sm" disabled={save.isPending || !current || (editing === "password" ? next.length < 8 : !email.trim())}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn btn-sm" onClick={close}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-center gap-2 pt-3">
          <button className="btn btn-sm" onClick={() => open("password")}>
            Change password
          </button>
          <button className="btn btn-sm" onClick={() => open("email")}>
            Change email
          </button>
          {save.isSuccess && <span className="text-xs text-emerald-700 dark:text-emerald-400">Saved.</span>}
        </div>
      )}
    </div>
  );
}

function TelegramCard({ me, botConfigured }: { me: Me; botConfigured: boolean }) {
  const [, setMe] = useMe();
  const confirm = useConfirm();
  const [linkUrl, setLinkUrl] = useState<string | null>(null);
  const link = useMutation({
    mutationFn: api.telegramLink,
    onSuccess: ({ url }) => {
      setLinkUrl(url);
      window.open(url, "_blank", "noopener");
    },
  });
  const verify = useMutation({
    mutationFn: api.telegramVerify,
    onSuccess: (m) => {
      setLinkUrl(null);
      setMe(m);
    },
  });
  const unlink = useMutation({ mutationFn: api.telegramUnlink, onSuccess: setMe });
  const test = useMutation({ mutationFn: () => api.testNotification("TELEGRAM") });

  return (
    <div className="card space-y-3 p-4">
      <div>
        <h2 className="font-semibold">Telegram alerts</h2>
        <p className="text-xs text-slate-500">Your price alerts are sent to your own Telegram chat.</p>
      </div>
      {!botConfigured ? (
        <p className="text-sm text-slate-500">
          <Dot ok={false} />
          Telegram isn't set up on this server (TELEGRAM_BOT_TOKEN).
        </p>
      ) : me.telegram_linked ? (
        <>
          <p className="text-sm">
            <Dot ok />
            Connected
          </p>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-sm" disabled={test.isPending} onClick={() => test.mutate()}>
              {test.isPending ? "Sending…" : "Send test"}
            </button>
            <button
              className="btn btn-sm"
              disabled={unlink.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: "Disconnect Telegram?",
                  message: "You'll stop getting alert messages until you connect again.",
                  confirmLabel: "Disconnect",
                  danger: true,
                });
                if (ok) unlink.mutate();
              }}
            >
              Disconnect
            </button>
          </div>
          {test.isSuccess && <p className="text-xs text-emerald-700 dark:text-emerald-400">Sent. Check Telegram.</p>}
          <ErrorText error={test.error ?? unlink.error} />
        </>
      ) : linkUrl ? (
        <>
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            <li>
              In Telegram, press <span className="font-medium">Start</span> in the chat with the bot.{" "}
              <a href={linkUrl} target="_blank" rel="noopener" className="text-teal-700 hover:underline dark:text-teal-400">
                Open the bot again
              </a>
            </li>
            <li>Come back here and confirm.</li>
          </ol>
          <button className="btn btn-primary btn-sm" disabled={verify.isPending} onClick={() => verify.mutate()}>
            {verify.isPending ? "Checking…" : "I've pressed Start"}
          </button>
          <ErrorText error={verify.error} />
        </>
      ) : (
        <>
          <p className="text-sm">
            <Dot ok={false} warn />
            Not connected. Alerts are still recorded in History, but no message is sent.
          </p>
          <button className="btn btn-primary btn-sm" disabled={link.isPending} onClick={() => link.mutate()}>
            {link.isPending ? "Opening…" : "Connect Telegram"}
          </button>
          <ErrorText error={link.error} />
        </>
      )}
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
      <div className="flex flex-wrap gap-2">
        <input className="input min-w-0 flex-1 sm:w-36 sm:flex-none" aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Symbol" />
        <input className="input num w-28 min-w-0" aria-label="Price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Price" />
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
