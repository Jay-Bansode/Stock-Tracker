import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { NavLink } from "react-router";
import { api } from "../api";
import { inMarketHoursIST, timeAgo } from "../format";
import { priceStore } from "../prices";
import { resetSession } from "../queryClient";
import type { SystemStatus } from "../types";

const nav = [
  { to: "/watchlists", label: "Watchlists" },
  { to: "/alerts", label: "Alerts" },
  { to: "/history", label: "History" },
  { to: "/settings", label: "Settings" },
];

/** Free-hosting mode: an external scheduler runs a check every minute during market hours. */
function pollIndicator(status: SystemStatus): [tone: string, label: string] {
  const poll = status.poll;
  if (!poll) return ["bg-amber-500", "Waiting for first check"];
  const ageSec = (Date.now() - Date.parse(poll.at)) / 1000;
  const ago = timeAgo(Date.parse(poll.at) / 1000);
  if (!poll.ok) return ["bg-red-500", `Last check failed · ${ago}`];
  if (!inMarketHoursIST()) return ["bg-slate-400", `Market closed · checked ${ago}`];
  if (ageSec > 180) return ["bg-red-500", `Checks stopped · last ${ago}`];
  return ["bg-emerald-500", `${poll.provider === "simulated" ? "Simulated" : "Checked"} · ${ago}`];
}

function FeedIndicator() {
  const { data } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10_000 });
  const mode = data?.mode;
  useEffect(() => {
    if (mode) priceStore.configure(mode === "cron" ? "poll" : "ws");
  }, [mode]);
  const engine = data?.engine;
  let tone = "bg-slate-400";
  let label = "Checking…";
  if (data?.mode === "cron") {
    [tone, label] = pollIndicator(data);
  } else if (data) {
    if (!engine || engine.heartbeat_age_sec > 30) {
      tone = "bg-red-500";
      label = "Engine offline";
    } else if (engine.connected) {
      tone = "bg-emerald-500";
      label = `${engine.provider === "simulated" ? "Simulated" : "Live"} · ${timeAgo(engine.last_tick_at)}`;
    } else if (!engine.market_window_open) {
      tone = "bg-slate-400";
      label = "Market closed";
    } else {
      tone = "bg-amber-500";
      label = "Feed reconnecting";
    }
  }
  return (
    <NavLink to="/settings" className="flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300" title="Market data status">
      <span className={`size-2 rounded-full ${tone}`} />
      {label}
    </NavLink>
  );
}

export default function Layout({ username, children }: { username: string; children: ReactNode }) {
  const qc = useQueryClient();
  const logout = async () => {
    try {
      await api.logout();
    } finally {
      await resetSession(qc);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
          <div className="flex items-center gap-2 font-semibold">
            <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
              <rect width="32" height="32" rx="7" className="fill-teal-700" />
              <path d="M7 21l6-6 4 4 8-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Tracker
          </div>
          <nav className="flex gap-1 overflow-x-auto">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap ${
                    isActive
                      ? "bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-300"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <FeedIndicator />
            <button className="btn btn-sm" onClick={logout} title={`Signed in as ${username}`}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
