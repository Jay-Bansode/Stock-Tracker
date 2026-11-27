import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "../queryClient";
import HistoryPage from "./HistoryPage";

const event = {
  id: 1, alert_id: 1, watchlist_id: 1, watchlist_name: "Long-Term", instrument_key: "NSE_EQ|A", trading_symbol: "RELIANCE",
  company_name: "Reliance", condition: "ABOVE", target_price: 1500, trigger_price: 1502, exchange_ts: null,
  triggered_at: "2026-11-20T05:00:00Z", notifications: [],
};

function renderPage() {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      const body = url.startsWith("/api/history") ? { items: [event], total: 1, page: 1, page_size: 50 } : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return urls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("HistoryPage sorting", () => {
  it("asks the server for the chosen order, from page 1, and the CSV export follows it", async () => {
    const urls = renderPage();
    await screen.findAllByText("RELIANCE");
    expect(urls.filter((u) => u.startsWith("/api/history"))[0]).not.toContain("sort=");

    fireEvent.click(screen.getByRole("button", { name: "Price at hit" }));
    await waitFor(() => expect(urls.at(-1)).toContain("sort=price&dir=desc"));
    expect(urls.at(-1)).toContain("page=1");
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", expect.stringContaining("sort=price&dir=desc"));

    fireEvent.click(screen.getByRole("button", { name: "Price at hit" }));
    await waitFor(() => expect(urls.at(-1)).toContain("sort=price&dir=asc"));
  });
});
