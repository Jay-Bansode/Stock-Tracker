export type Condition = "ABOVE" | "BELOW";
export type TriggerMode = "ONCE" | "REPEAT";
export type AlertStatus = "ACTIVE" | "TRIGGERED" | "DISABLED";

export interface Instrument {
  instrument_key: string;
  trading_symbol: string;
  name: string;
  exchange: string;
  segment: string;
  instrument_type: string;
}

export interface Alert {
  id: number;
  watchlist_item_id: number;
  condition: Condition;
  target_price: number;
  trigger_mode: TriggerMode;
  rearm_pct: number;
  cooldown_sec: number;
  status: AlertStatus;
  last_triggered_at: string | null;
  last_trigger_price: number | null;
  trigger_count: number;
  note: string | null;
  created_at: string;
}

export interface AlertSaved extends Alert {
  current_price: number | null;
  already_met: boolean;
}

export interface AlertWithContext extends Alert {
  watchlist_id: number;
  watchlist_name: string;
  instrument: Instrument;
}

export interface AlertInput {
  condition: Condition;
  target_price: number;
  trigger_mode: TriggerMode;
  rearm_pct: number;
  cooldown_sec: number;
  note: string | null;
}

export interface Watchlist {
  id: number;
  name: string;
  description: string | null;
  sort_order: number;
  item_count: number;
  active_alerts: number;
  triggered_alerts: number;
  created_at: string;
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  instrument: Instrument;
  notes: string | null;
  added_at: string;
  alerts: Alert[];
}

export interface NotificationRow {
  id: number;
  channel: "TELEGRAM" | "WHATSAPP";
  status: "PENDING" | "SENDING" | "SENT" | "FAILED";
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  next_attempt_at: string;
}

export interface AlertEvent {
  id: number;
  alert_id: number | null;
  watchlist_id: number | null;
  watchlist_name: string;
  instrument_key: string;
  trading_symbol: string;
  company_name: string;
  condition: Condition;
  target_price: number;
  trigger_price: number;
  exchange_ts: string | null;
  triggered_at: string;
  notifications: NotificationRow[];
}

export interface EventPage {
  items: AlertEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface Price {
  k: string;
  p: number;
  c: number | null;
  t: number;
}

export interface PollStatus {
  at: string;
  provider: string;
  ok: boolean;
  error: string | null;
  market_open: boolean;
  polled: number;
  rules: number;
  events: number;
  sent: number;
  duration_ms?: number;
}

export interface SystemStatus {
  mode?: "services" | "cron";
  poll?: PollStatus | null;
  engine: {
    provider: string;
    connected: boolean;
    market_window_open: boolean;
    market_status: Record<string, string>;
    subscriptions: number;
    active_rules: number;
    last_tick_at: number | null;
    heartbeat_age_sec: number;
  } | null;
  provider: "simulated" | "upstox";
  upstox_token_set: boolean;
  upstox_token_expires_on: string | null;
  upstox_token_days_left: number | null;
  channels: { TELEGRAM: boolean; WHATSAPP: boolean };
  alerts: { active: number; triggered: number; fired_today: number };
}
