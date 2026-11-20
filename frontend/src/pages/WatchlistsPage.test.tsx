import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "../queryClient";
import WatchlistsPage from "./WatchlistsPage";

const watchlists = [
  { id: 1, name: "Long-Term", description: null, sort_order: 1, item_count: 2, active_alerts: 1, triggered_alerts: 0, created_at: "2026-11-01T00:00:00Z" },
  { id: 2, name: "Intraday", description: null, sort_order: 2, item_count: 0, active_alerts: 0, triggered_alerts: 0, created_at: "2026-11-01T00:00:00Z" },
];

const instrument = (symbol: string, key: string) => ({
  instrument_key: key, trading_symbol: symbol, name: `${symbol} Ltd`, exchange: "NSE", segment: "NSE_EQ", instrument_type: "EQ",
});

const items = [
  {
    id: 10, watchlist_id: 1, instrument: instrument("RELIANCE", "NSE_EQ|A"), notes: null, added_at: "2026-11-01T00:00:00Z",
    alerts: [{
      id: 100, watchlist_item_id: 10, condition: "ABOVE", target_price: 1500, trigger_mode: "REPEAT", rearm_pct: 0.5, cooldown_sec: 900,
      check_from: "15:15:00", check_until: "15:15:00", status: "ACTIVE", last_triggered_at: null, last_trigger_price: null,
      trigger_count: 0, note: null, created_at: "2026-11-01T00:00:00Z",
    }],
  },
  { id: 11, watchlist_id: 1, instrument: instrument("HDFCBANK", "NSE_EQ|B"), notes: null, added_at: "2026-11-01T00:00:00Z", alerts: [] },
];

function renderPage() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url === "/api/watchlists" ? watchlists : url === "/api/watchlists/1/items" ? items : null;
      if (body === null) throw new Error(`unexpected ${url}`);
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={["/watchlists/1"]}>
        <Routes>
          <Route path="/watchlists/:id" element={<WatchlistsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("WatchlistsPage", () => {
  it("gives every stock its alert and remove actions in a single row", async () => {
    renderPage();
    const rows = await screen.findAllByRole("listitem", { name: (_, el) => !!el.querySelector("button[title='Remove from watchlist']") });
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(within(row).getByRole("button", { name: "+ Alert" })).toBeInTheDocument();
      expect(within(row).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    }
    expect(within(rows[0]).getByText(/at 3:15 PM/)).toBeInTheDocument(); // timed alert chip
  });

  it("opens the alert form under the stock", async () => {
    renderPage();
    const hdfc = (await screen.findByText("HDFCBANK")).closest("li")!;
    fireEvent.click(within(hdfc).getByRole("button", { name: "+ Alert" }));
    expect(within(hdfc).getByRole("button", { name: "Add alert" })).toBeInTheDocument();
  });

  it("lists every watchlist for switching", async () => {
    renderPage();
    expect(await screen.findByRole("button", { name: /Intraday/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Long-Term/ })).toHaveAttribute("aria-current", "page");
  });
});
