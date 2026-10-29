# Tracker: stock watchlists & price alerts

Personal dashboard for multiple watchlists with live NSE/BSE prices from **Upstox**. When a price
condition you set is met, it sends a notification to **Telegram** and **WhatsApp**.

- Multiple watchlists. The same stock can sit in several of them with different targets.
- Every alert belongs to one *watchlist + stock* pair, so each fires and notifies on its own. If
  Reliance is in "Long-Term" (≥ ₹1,500) and "Intraday" (≥ ₹1,480), you get two separate messages.
- No duplicate notifications. An alert fires once, then waits for a manual re-arm (or, in Repeat
  mode, re-arms automatically after the price moves back past a band and a cooldown).
- Full alert history: which stock hit which target, in which watchlist, at what price and time,
  plus whether each Telegram/WhatsApp message was delivered. Exportable as CSV.

```
🔔 Stock Price Alert Triggered

• Watchlist: Long-Term Stocks
• Stock: Reliance Industries (NSE: RELIANCE)
• Target Price: ₹1,500 (Above)
• Current Price: ₹1,502
• Status: Target Hit
• Time: 29 Oct 2026, 10:42:15 IST
```

## How it works

```
Upstox V3 WebSocket ──ticks──▶ engine ──(match)──▶ Postgres: alert → TRIGGERED
 (or simulator)                  │                  + alert_events row (history)
                                 │                  + notifications rows (outbox, 1 per channel)
                                 ▼                              │ LISTEN/NOTIFY
                        Redis price cache ◀── api ◀── browser    ▼
                        + pub/sub ticks ──▶ /ws/prices     notifier ──▶ Telegram / WhatsApp
```

| Service | Role |
|---|---|
| `engine` | Holds the single Upstox feed connection, checks every tick against an in-memory alert index, and records triggers. A Postgres advisory lock keeps a second copy on standby. |
| `notifier` | Sends queued notifications with retries and backoff. Telegram and WhatsApp run independently. |
| `api` | REST API + live-price WebSocket for the dashboard. |
| `web` | React dashboard (nginx), proxies `/api` and `/ws`. |
| `postgres`, `redis` | Storage; price cache and tick fan-out. |

The rule against duplicates lives in the database. A trigger is the conditional update
`UPDATE alerts SET status='TRIGGERED' WHERE id=… AND status='ACTIVE'`, done in the same
transaction that writes the history row and the outbox rows. Repeated ticks, reconnect snapshots
and restarts therefore can never fire the same alert twice. Each outbox row is unique per
(event, channel).

## Quick start (simulated prices, no accounts needed)

Requires Docker Desktop.

```bash
cp .env.example .env          # defaults: simulated prices, login admin / admin
docker compose up -d --build
```

Open **http://localhost:8080** and sign in with `admin` / `admin`.

1. Create watchlists, e.g. *Long-Term Stocks*, *Intraday Stocks*, *Banking Stocks*.
2. Add stocks with the search box. The full NSE/BSE list is downloaded from Upstox on first start.
3. Click **+ Alert** on a stock, then choose *at or above* / *at or below* and a target price.
4. Go to **Settings → Simulator**, push a price (e.g. `RELIANCE` → `1502`), and watch
   **History**.

With `SIMULATED_RANDOM_WALK=true`, prices drift slightly every second. Set it to `false` if you
only want the prices you push.

Before using it for real, change the login: run `docker compose run --rm api python -m app.cli
hash-password`, put the printed `ADMIN_PASSWORD_HASH='…'` line (keep the single quotes) in `.env`,
remove `ADMIN_PASSWORD`, and set a long random `SECRET_KEY`.

After any `.env` change: `docker compose up -d` (it recreates only the services that changed).

## Going live with Upstox

Tracker only reads market data, so it uses Upstox's **Analytics Token**. It is read-only, valid
for one year, and needs no daily login and no static IP.

1. Sign in at the [Upstox Developer portal](https://account.upstox.com/developer/apps) → **Analytics**
   tab → **Generate Token**. Note the expiry date it shows.
2. In `.env`:
   ```
   MARKET_DATA_PROVIDER=upstox
   UPSTOX_ANALYTICS_TOKEN=eyJ...
   UPSTOX_TOKEN_EXPIRES_ON=2027-10-28
   ```
3. `docker compose up -d`, then check **Settings**. During market hours the feed shows
   *Connected*.

How the live feed behaves:
- Connects only between `MARKET_OPEN` and `MARKET_CLOSE` (IST, default 09:00–15:40) on NSE trading
  days. Holidays come from the Upstox holiday API.
- Uses one WebSocket in `ltpc` mode for every stock in any watchlist. Normal Upstox accounts allow
  5,000 instruments; `MAX_SUBSCRIPTIONS` defaults to 2,000.
- Reconnects automatically with backoff. The snapshot Upstox sends after each reconnect is
  evaluated like a normal tick, so a target crossed while disconnected still fires.
- Sends a Telegram warning if the feed is down for more than 5 minutes in market hours, if Upstox
  rejects the token, and daily during the 7 days before the token expires.
- Outside market hours, prices for newly added stocks are filled from the REST LTP API for display.
  Only live-feed ticks trigger alerts.

## Telegram setup

1. In Telegram, message **@BotFather** → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Open your new bot and press **Start** (or send any message).
3. Find your chat id:
   ```bash
   docker compose run --rm api python -m app.notify.telegram
   # TELEGRAM_CHAT_ID=123456789    (yourname)
   ```
4. Put `TELEGRAM_CHAT_ID` in `.env`, `docker compose up -d`, then **Settings → Telegram → Send test**.

To send alerts to a group instead, add the bot to the group, post a message there, and use the
(negative) group id the helper prints.

## WhatsApp setup (Meta WhatsApp Cloud API)

WhatsApp only lets businesses start a conversation with a **pre-approved message template**, so
alerts go out as a template named `stock_price_alert`.

1. Create an app at [developers.facebook.com](https://developers.facebook.com/apps) (type
   *Business*) and add the **WhatsApp** product. Meta gives you a test sender number. You can use
   it, or add your own number.
2. From **WhatsApp → API Setup**, copy the **Phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`.
   Add your personal number as a recipient (the test number can message up to 5 verified
   numbers) → `WHATSAPP_TO` (country code, no `+`, e.g. `919876543210`).
3. Create a **permanent token**: Business Settings → *System users* → add a system user → assign
   the app and the WhatsApp account → *Generate token* with `whatsapp_business_messaging`
   permission → `WHATSAPP_TOKEN`. The temporary token on the API Setup page expires in 24 hours.
4. **WhatsApp Manager → Message templates → Create template**:
   - Category **Utility**, name `stock_price_alert`, language **English** (`en`).
   - Body (six variables, in this order):
     ```
     🔔 Stock Price Alert Triggered

     Watchlist: {{1}}
     Stock: {{2}}
     Target Price: {{3}}
     Current Price: {{4}}
     Status: {{5}}
     Time: {{6}}

     Sent by your Tracker price alerts.
     ```
   - Sample values: `Long-Term Stocks`, `Reliance Industries (NSE: RELIANCE)`,
     `₹1,500 (Above)`, `₹1,502`, `Target Hit`, `29 Oct 2026, 10:42:15 IST`.
   - Submit and wait for approval (usually minutes, sometimes up to a day).
5. `docker compose up -d`, then **Settings → WhatsApp → Send test**.

If you named the template differently, or approved it in another language code (e.g. `en_US`), set
`WHATSAPP_TEMPLATE` / `WHATSAPP_TEMPLATE_LANG` to match. Meta may charge a small per-message
fee for utility templates in India. Check current rates in WhatsApp Manager. Operational warnings
(feed down, token expiry) go to Telegram only, since WhatsApp would need a separate template.

## Alert options

| Option | Meaning |
|---|---|
| At or above / at or below | Fires when the last traded price is `≥` / `≤` the target. Touching the target counts. |
| Once (default) | After firing, the alert shows **Target hit** and stays quiet until you click **Re-arm**. |
| Re-arm automatically | After firing, re-arms once the price moves back past the target by the *re-arm band* (default 0.5%) **and** the *cooldown* (default 15 min) has passed. This prevents spam when a price hovers at the target. |

If the price already meets the condition when you save an alert, the form warns you that it will
fire on the next tick. Changing an alert's condition or target re-arms it. Deleting an alert or a
watchlist keeps its history, because history rows store names and prices as they were.

## Running it 24/7

Alerts only fire while the stack is running, so leave Docker running during market hours, or
deploy the same `docker-compose.yml` to a small VPS. All ports bind to `127.0.0.1`. For remote
access, put it behind an HTTPS reverse proxy (Caddy, nginx, Cloudflare Tunnel) and set
`COOKIE_SECURE=true`.

Useful commands:

```bash
docker compose ps                         # health of all services
docker compose logs -f engine notifier    # live feed + delivery logs
docker compose run --rm api python -m app.cli sync-instruments   # refresh stock list now
```

## Free hosting (Render + Supabase + cron-job.org)

Free web hosts don't run always-on background processes, so this setup uses a different mode,
`RUN_MODE=cron`. A free scheduler calls Tracker **once a minute** during market hours. Each call:
1. Fetches prices from the Upstox REST API.
2. Checks every alert, with the same no-duplicates guarantee as the Docker setup.
3. Sends the Telegram/WhatsApp messages.

Everything runs in **one** container with no Redis.

| Service (free tier) | Role |
|---|---|
| [Render](https://render.com) web service | Runs the API + dashboard from `deploy/render/Dockerfile` |
| [Supabase](https://supabase.com) Postgres | Database (watchlists, alerts, history, latest prices) |
| [cron-job.org](https://cron-job.org) | Calls `/api/cron/poll` every minute |

**Trade-offs compared with the Docker setup:**
- An alert can arrive up to about 1 minute after the price hits.
- A target touched briefly *between* two checks is still caught, using Upstox's 1-minute high/low.
  The message then shows that high/low as the price.
- Dashboard prices refresh every 20 s and are up to a minute old.
- Render's free service sleeps after 15 minutes without visitors. The scheduler wakes it each
  morning, but the first dashboard visit after a quiet spell takes about a minute to load.

### 1. Put the code on GitHub
Create a **private** repository and push this project. `.env` is git-ignored; your secrets go
into Render instead.

### 2. Database: Supabase
1. Create a project at [supabase.com](https://supabase.com) in region **Mumbai (ap-south-1)**.
   Save the database password it shows.
2. Click **Connect** and copy the **Session pooler** connection string
   (`postgresql://postgres.<id>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`).
   - Use the session pooler: Render can't reach Supabase's direct (IPv6-only) address, and the
     transaction pooler on port 6543 breaks the lock that prevents overlapping runs.
   - Add `?sslmode=require` at the end. Tracker converts this URL format automatically.

Tracker creates its tables on first start. Supabase pauses a free project only after 7 days with
no activity, and the minute-by-minute checks keep it active on trading weeks.

### 3. App: Render
1. Render → **New → Blueprint** → select your repository. Render reads `render.yaml` and creates
   a free web service in Singapore.
2. Fill in the values it asks for:
   - **DATABASE_URL:** the Supabase URI from step 2.
   - **ADMIN_PASSWORD_HASH:** run `cd backend && .venv\Scripts\python -m app.cli hash-password`
     locally and paste the hash **without** the surrounding quotes.
   - **Upstox / Telegram / WhatsApp:** the same values as your `.env`.
     - `UPSTOX_TOKEN_EXPIRES_ON` accepts `29/09/2027`.
     - Leave the WhatsApp fields empty if you haven't set it up yet.
3. Deploy. When it's live, open `https://<your-service>.onrender.com` and sign in as `admin`.
   - **Stock search:** the stock list downloads in the background on first start, so search
     works after about a minute.
   - **CRON_SECRET:** copy the auto-generated value from the service's **Environment** tab. You
     need it next.

### 4. Scheduler: cron-job.org
Create a free account and add two jobs.

| Job | URL | Schedule (time zone **Asia/Kolkata**) |
|---|---|---|
| Check prices | `https://<your-service>.onrender.com/api/cron/poll` | Every minute, Mon–Fri, hours 9–15 |
| Refresh stock list | `https://<your-service>.onrender.com/api/cron/instruments` | Daily 08:30, Mon–Fri |

For both jobs, open **Advanced** and set:
- **Request method:** `POST`
- **Header:** `X-Cron-Secret: <your CRON_SECRET>`
- **Notify on failure:** on (so you get an e-mail if checks stop)

The 09:00 call wakes the sleeping service before the 09:15 market open. Calls outside 09:00–15:40
IST, or on NSE holidays, return quickly without fetching prices. Any queued messages are still
delivered.

### 5. Check it
- **Settings** shows *Mode: Free hosting* and the time and result of the **Last check**.
  - The header turns red if checks stop during market hours.
  - Use the job's **Test run** button in cron-job.org to trigger a check without waiting.
- **Settings → Telegram → Send test** confirms notifications work from the hosted app.

To try cron mode without Upstox, set `MARKET_DATA_PROVIDER=simulated` and use
**Settings → Simulator**.

## Development

```bash
# infrastructure only
docker compose up -d postgres redis

# backend (Python 3.12)
cd backend
python -m venv .venv && .venv/Scripts/activate        # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload       # API on :8000
python -m app.engine                # in another terminal
python -m app.notify                # in another terminal
pytest                              # unit + integration tests (needs postgres/redis above)

# frontend
cd frontend
npm install
npm run dev                         # http://localhost:5173, proxies /api and /ws to :8000
npm test
```

Tests cover:
- the evaluator (boundaries, re-arm band, cooldown)
- the example scenario (same stock in two watchlists)
- dedupe across repeated ticks, restarts and 8 concurrent triggers
- the outbox worker (retry, 429 `retry_after`, permanent failures, stale-row recovery, channel
  independence)
- Telegram/WhatsApp error handling
- protobuf decoding and the Upstox client (subscribe, reconnect + re-authorize, subscription
  diffs) against a fake WebSocket server
- the HTTP API
