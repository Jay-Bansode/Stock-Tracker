import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { Price } from "./types";

type Listener = () => void;
export type PriceTransport = "ws" | "poll";

const POLL_MS = 20_000;

/**
 * Live prices for the whole app. Components register the instrument keys they display
 * (ref-counted). The always-on deployment streams them over one WebSocket to /ws/prices; the
 * free-hosting (cron) deployment has no stream, so prices are polled from /api/quotes instead.
 */
export class PriceStore {
  private prices = new Map<string, Price>();
  private snapshot = new Map<string, Price>();
  private listeners = new Set<Listener>();
  private refs = new Map<string, number>();
  private ws: WebSocket | null = null;
  private retry = 1000;
  private connected = false;
  private statusListeners = new Set<Listener>();
  private transport: PriceTransport | null = null; // unknown until the server says
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  getSnapshot = () => this.snapshot;

  subscribeStatus = (listener: Listener) => {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  };
  isConnected = () => this.connected;

  retain(keys: string[]) {
    let changed = false;
    for (const k of keys) {
      const n = this.refs.get(k) ?? 0;
      this.refs.set(k, n + 1);
      if (n === 0) changed = true;
    }
    if (changed) {
      this.sendSubscription();
      if (this.transport === "poll" && this.pollTimer) void this.poll();
    }
    this.start();
  }

  /** Pick the transport once /api/system/status reports the deployment mode. */
  configure(transport: PriceTransport) {
    if (transport === this.transport) return;
    this.stop();
    this.transport = transport;
    this.start();
  }

  private start() {
    if (!this.refs.size) return;
    if (this.transport === "ws") this.ensureSocket();
    else if (this.transport === "poll" && !this.pollTimer) {
      this.pollTimer = setInterval(() => void this.poll(), POLL_MS);
      void this.poll();
    }
  }

  private stop() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = null;
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  private async poll() {
    const keys = [...this.refs.keys()];
    if (!keys.length) return;
    try {
      const res = await fetch(`/api/quotes?keys=${encodeURIComponent(keys.join(","))}`, {
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as Record<string, Price>;
      for (const p of Object.values(data)) this.prices.set(p.k, p);
      this.setConnected(true);
      this.emit();
    } catch {
      this.setConnected(false);
    }
  }

  release(keys: string[]) {
    let changed = false;
    for (const k of keys) {
      const n = (this.refs.get(k) ?? 1) - 1;
      if (n <= 0) {
        this.refs.delete(k);
        changed = true;
      } else this.refs.set(k, n);
    }
    if (changed) this.sendSubscription();
  }

  private emit() {
    this.snapshot = new Map(this.prices);
    this.listeners.forEach((l) => l());
  }

  private setConnected(v: boolean) {
    this.connected = v;
    this.statusListeners.forEach((l) => l());
  }

  private sendSubscription() {
    const ws = this.ws;
    if (ws && ws.readyState === ws.OPEN) {
      ws.send(JSON.stringify({ subscribe: [...this.refs.keys()] }));
    }
  }

  private ensureSocket() {
    if (this.ws || typeof WebSocket === "undefined") return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/prices`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 1000;
      this.setConnected(true);
      this.sendSubscription();
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as { type: string; prices: Price[] };
      for (const p of msg.prices) this.prices.set(p.k, p);
      this.emit();
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // closed deliberately via disconnect()
      this.ws = null;
      this.setConnected(false);
      if (this.refs.size === 0) return;
      setTimeout(() => this.ensureSocket(), this.retry);
      this.retry = Math.min(this.retry * 2, 30000);
    };
  }

  /** On sign-out: stop streaming/polling without reconnecting and forget cached prices. */
  disconnect() {
    this.stop();
    this.setConnected(false);
    this.prices.clear();
    this.emit();
  }

  /** Called after login so a socket rejected while signed out gets a fresh attempt. */
  reconnect() {
    this.disconnect();
    this.start();
  }
}

export const priceStore = new PriceStore();

export function usePrices(keys: string[]): Map<string, Price> {
  const joined = useMemo(() => [...new Set(keys)].sort().join(","), [keys]);
  useEffect(() => {
    if (!joined) return;
    const list = joined.split(",");
    priceStore.retain(list);
    return () => priceStore.release(list);
  }, [joined]);
  return useSyncExternalStore(priceStore.subscribe, priceStore.getSnapshot);
}

export function useLiveConnection(): boolean {
  return useSyncExternalStore(priceStore.subscribeStatus, priceStore.isConnected);
}
