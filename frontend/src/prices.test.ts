import { afterEach, describe, expect, it, vi } from "vitest";
import { PriceStore } from "./prices";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PriceStore in poll mode (free hosting)", () => {
  it("polls /api/quotes for the retained keys instead of opening a WebSocket", async () => {
    vi.useFakeTimers();
    const ws = vi.fn();
    vi.stubGlobal("WebSocket", ws);
    let ltp = 1500;
    const fetchMock = vi.fn(async (url: string) => {
      const keys = new URL(url, "http://x").searchParams.get("keys")!.split(",");
      return new Response(JSON.stringify(Object.fromEntries(keys.map((k) => [k, { k, p: ltp, c: 1490, t: 1 }]))));
    });
    vi.stubGlobal("fetch", fetchMock);

    const store = new PriceStore();
    store.retain(["NSE_EQ|A"]);
    expect(fetchMock).not.toHaveBeenCalled(); // transport unknown until the server says

    store.configure("poll");
    await vi.waitFor(() => expect(store.getSnapshot().get("NSE_EQ|A")?.p).toBe(1500));
    expect(store.isConnected()).toBe(true);

    ltp = 1502;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(store.getSnapshot().get("NSE_EQ|A")?.p).toBe(1502);
    expect(ws).not.toHaveBeenCalled();

    store.retain(["NSE_EQ|B"]); // a newly shown stock is fetched right away, not in 20 s
    await vi.waitFor(() => expect(store.getSnapshot().has("NSE_EQ|B")).toBe(true));
    expect(decodeURIComponent(String(fetchMock.mock.calls.at(-1)![0]))).toContain("NSE_EQ|A,NSE_EQ|B");

    store.disconnect();
    const calls = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock.mock.calls.length).toBe(calls); // polling stops on sign-out
  });
});
