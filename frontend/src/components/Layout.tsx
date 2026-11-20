import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router";
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
  // Phones show just the dot (label in the tooltip / for screen readers); wider screens show the text.
  return (
    <NavLink
      to="/settings"
      className="flex shrink-0 items-center gap-2 rounded-full border border-slate-200 p-2 text-xs whitespace-nowrap text-slate-600 sm:px-3 sm:py-1 dark:border-slate-700 dark:text-slate-300"
      title={`Market data: ${label}`}
    >
      <span className={`size-2.5 rounded-full sm:size-2 ${tone}`} aria-hidden />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </NavLink>
  );
}

export default function Layout({ username, children }: { username: string; children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = async () => {
    try {
      await api.logout();
    } finally {
      // A deliberate sign-out starts fresh at /login. (An expired session keeps its URL, so
      // signing in again returns to the same page.) The state tells the still-signed-in routes
      // not to bounce /login back to /watchlists while the session is being cleared.
      navigate("/login", { replace: true, state: { signingOut: true } });
      await resetSession(qc);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:gap-6">
          <div className="flex shrink-0 items-center gap-2 font-semibold">
            <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
              <rect width="32" height="32" rx="7" className="fill-teal-700" />
              <path d="M7 21l6-6 4 4 8-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Tracker
          </div>
          <nav aria-label="Main" className="hidden gap-1 sm:flex">
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
          <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
            <FeedIndicator />
            <span className="hidden max-w-40 truncate text-sm text-slate-600 md:inline dark:text-slate-300">{username}</span>
            <button className="btn btn-sm shrink-0 whitespace-nowrap" onClick={logout} title={`Signed in as ${username}`}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      {/* Phones: room at the bottom for the tab bar (plus the iPhone home indicator). */}
      <main className="mx-auto max-w-7xl px-4 pt-4 pb-[calc(5rem+env(safe-area-inset-bottom))] sm:py-6">{children}</main>
      <nav
        aria-label="Main (mobile)"
        className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden dark:border-slate-800 dark:bg-slate-950/95"
      >
        {nav.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) =>
              `flex h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium ${
                isActive ? "text-teal-700 dark:text-teal-300" : "text-slate-500 dark:text-slate-400"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span className={`h-1 w-8 rounded-full ${isActive ? "bg-teal-600 dark:bg-teal-400" : "bg-transparent"}`} aria-hidden />
                {n.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
