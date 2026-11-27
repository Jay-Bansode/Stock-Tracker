import type {
  AlertInput,
  AlertSaved,
  AlertStatus,
  AlertWithContext,
  EventPage,
  Instrument,
  Me,
  SystemStatus,
  Watchlist,
  WatchlistItem,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((d: { msg: string }) => d.msg).join("; ")
            : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export interface HistoryFilters {
  watchlist_id?: number;
  symbol?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export const api = {
  me: () => request<Me>("GET", "/auth/me"),
  login: (username: string, password: string) => request<Me>("POST", "/auth/login", { username, password }),
  logout: () => request<void>("POST", "/auth/logout"),
  register: (username: string, email: string, password: string) =>
    request<Me>("POST", "/auth/register", { username, email, password }),
  forgotPassword: (email: string) => request<{ detail: string }>("POST", "/auth/forgot-password", { email }),
  resetPassword: (token: string, password: string) => request<Me>("POST", "/auth/reset-password", { token, password }),
  changePassword: (current_password: string, new_password: string) =>
    request<Me>("POST", "/auth/change-password", { current_password, new_password }),
  changeEmail: (email: string, current_password: string) =>
    request<Me>("PUT", "/account/email", { email, current_password }),
  telegramLink: () => request<{ url: string; bot: string }>("POST", "/account/telegram/link"),
  telegramVerify: () => request<Me>("POST", "/account/telegram/verify"),
  telegramUnlink: () => request<Me>("DELETE", "/account/telegram"),

  watchlists: () => request<Watchlist[]>("GET", "/watchlists"),
  createWatchlist: (name: string, description?: string) =>
    request<Watchlist>("POST", "/watchlists", { name, description }),
  updateWatchlist: (id: number, patch: Partial<Pick<Watchlist, "name" | "description">>) =>
    request<Watchlist>("PATCH", `/watchlists/${id}`, patch),
  deleteWatchlist: (id: number) => request<void>("DELETE", `/watchlists/${id}`),
  reorderWatchlists: (ids: number[]) => request<void>("PUT", "/watchlists/order", { ids }),

  items: (watchlistId: number) => request<WatchlistItem[]>("GET", `/watchlists/${watchlistId}/items`),
  addItem: (watchlistId: number, instrument_key: string) =>
    request<WatchlistItem>("POST", `/watchlists/${watchlistId}/items`, { instrument_key }),
  updateItem: (watchlistId: number, itemId: number, patch: { bought_on: string | null }) =>
    request<WatchlistItem>("PATCH", `/watchlists/${watchlistId}/items/${itemId}`, patch),
  removeItem: (watchlistId: number, itemId: number) =>
    request<void>("DELETE", `/watchlists/${watchlistId}/items/${itemId}`),

  alerts: (filters: { status?: AlertStatus; watchlist_id?: number } = {}) =>
    request<AlertWithContext[]>("GET", `/alerts${qs({ ...filters })}`),
  createAlert: (itemId: number, input: AlertInput) =>
    request<AlertSaved>("POST", `/watchlist-items/${itemId}/alerts`, input),
  updateAlert: (id: number, patch: Partial<AlertInput>) =>
    request<AlertSaved>("PATCH", `/alerts/${id}`, patch),
  rearmAlert: (id: number) => request<AlertSaved>("POST", `/alerts/${id}/rearm`),
  disableAlert: (id: number) => request<AlertSaved>("POST", `/alerts/${id}/disable`),
  deleteAlert: (id: number) => request<void>("DELETE", `/alerts/${id}`),

  search: (q: string) => request<Instrument[]>("GET", `/instruments/search${qs({ q })}`),

  history: (f: HistoryFilters) => request<EventPage>("GET", `/history${qs({ ...f })}`),
  historyCsvUrl: (f: HistoryFilters) => `/api/history/export.csv${qs({ ...f, page: undefined, page_size: undefined })}`,
  retryNotification: (id: number) => request<{ status: string }>("POST", `/notifications/${id}/retry`),

  status: () => request<SystemStatus>("GET", "/system/status"),
  testNotification: (channel: string) =>
    request<{ ok: boolean; provider_message_id: string }>("POST", "/system/test-notification", { channel }),
  injectTicks: (prices: Record<string, number>) =>
    request<{ published: { k: string; p: string }[]; events?: number; sent?: number }>("POST", "/dev/ticks", prices),
};
