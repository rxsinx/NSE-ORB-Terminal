# 📡 NSE ORB Terminal — Streamlit + Twelve Data

A production-grade **Opening Range Breakout (ORB) scanner** for NSE-listed equities,
built with Streamlit and powered by the **Twelve Data API**.

---

## Features

| Feature | Details |
|---------|---------|
| **Stock Universe** | 300+ NSE symbols across Nifty 50, Next 50, Midcap 150, Smallcap 250 |
| **CMP Filter** | Only stocks with live CMP > ₹500 (configurable) |
| **ORB Capture** | 9:15 AM 15-min candle → locks High & Low |
| **Live Prices** | WebSocket (real-time ticks) or REST polling |
| **RSI (Daily)** | Fetched via Twelve Data `/rsi` endpoint |
| **Breakout Alerts** | Auto-fires when CMP crosses ORB High or Low |
| **Market Phases** | Pre-Open → ORB Window → Monitor → Close (IST) |
| **Intraday Chart** | Candlestick + ORB bands + Volume (5-min) |
| **Analytics** | Status donut, RSI histogram, sector bar, scatter, alert timeline |
| **Export** | Download alert log as CSV |
| **Demo Mode** | Fully functional without an API key |

---

## Quick Start

### 1. Clone / download
```bash
git clone https://github.com/yourrepo/nse-orb-terminal
cd nse-orb-terminal
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Get a Twelve Data API key
Sign up free at **https://twelvedata.com**
- Free plan: 800 API credits/day, 8 req/min
- For WebSocket streaming: requires a paid plan

### 4. Run
```bash
streamlit run app.py
```

### 5. In the app
1. Paste your API key in the sidebar → click **TEST** to verify
2. Choose **Live (WebSocket)** or **REST Poll**
3. Set CMP minimum (default ₹500)
4. Click **▶ SCAN / CONNECT**

---

## Project Structure

```
nse_orb_terminal/
│
├── app.py                      ← Main Streamlit application
│
├── utils/
│   ├── __init__.py
│   ├── twelvedata_client.py    ← REST + WebSocket API client
│   ├── nse_universe.py         ← Full NSE stock universe (300+ symbols)
│   ├── orb_engine.py           ← ORB logic, state, breakout detection
│   └── charts.py               ← Plotly chart builders
│
├── .streamlit/
│   └── config.toml             ← Dark theme config
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## Twelve Data API Endpoints Used

| Endpoint | Purpose | Call Frequency |
|----------|---------|----------------|
| `/quote` | Batch live prices (up to 80 symbols/call) | On scan + REST poll cycle |
| `/time_series?interval=15min` | 9:15 AM ORB candle | Once at scan time |
| `/rsi?interval=1day` | Daily RSI(14) | Once at scan time |
| `/time_series?interval=5min` | Intraday chart (on demand) | Per stock detail view |
| `wss://ws.twelvedata.com` | Real-time price ticks | Live (WebSocket mode) |

### Free Plan Limits
- 800 API credits/day
- 8 requests/minute
- RSI limited to first 40 symbols by default (adjustable in code)
- WebSocket requires a paid plan

---

## Market Schedule (IST)

| Phase | Time | Terminal Action |
|-------|------|----------------|
| Pre-Market | Before 09:00 | Terminal loads, no live data |
| Pre-Open | 09:00–09:14 | Pre-open auction prices |
| **ORB Window** | **09:15–09:29** | **Captures 15-min ORB candle** |
| **Monitor** | **09:30–15:29** | **Live alerts for breakouts/breakdowns** |
| Closing | 15:30 | Market closes, final alert summary |

---

## Status Definitions

| Status | Meaning |
|--------|---------|
| `ORB_SET` | CMP inside the ORB range |
| `WATCHING_HIGH` | CMP within 0.3% below ORB High |
| `WATCHING_LOW` | CMP within 0.3% above ORB Low |
| `BREAKOUT` | CMP has crossed **above** ORB High → alert fired |
| `BREAKDOWN` | CMP has crossed **below** ORB Low → alert fired |

---

## Configuration

All settings are adjustable in the sidebar at runtime:

| Setting | Default | Description |
|---------|---------|-------------|
| CMP Min (₹) | 500 | Only scan stocks above this price |
| RSI Period | 14 | Daily RSI period |
| Auto-refresh | 30s | REST poll interval |
| Data Source | REST Poll | Live WS / REST Poll / Demo |

---

## Deploying to Streamlit Cloud

1. Push to GitHub
2. Go to **share.streamlit.io** → New app
3. Add `TWELVE_DATA_API_KEY` as a secret in **App Settings → Secrets**
4. In `app.py`, load the key with:
   ```python
   import os
   api_key = os.environ.get("TWELVE_DATA_API_KEY", "")
   ```

---

## Disclaimer

This tool is for **educational and informational purposes only**.
It does not constitute financial advice. Always do your own research
before making trading decisions. Past ORB patterns do not guarantee
future performance.
