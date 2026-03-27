"""
app.py  —  NSE ORB Terminal  (Streamlit + Twelve Data)
═══════════════════════════════════════════════════════
Run:  streamlit run app.py

Architecture:
  • st.session_state holds: engine (ORBEngine), client (TwelveDataClient),
    streamer (TDWebSocketStreamer), scan metadata, config
  • Sidebar: API key entry, config, scan/connect controls
  • Main panel: live stock table, stats, charts
  • Auto-refresh via streamlit_autorefresh
"""

import time
import logging
import threading
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# ── Local imports ────────────────────────────────────────────
from utils.twelvedata_client import TwelveDataClient, TDWebSocketStreamer
from utils.nse_universe import get_universe, all_symbols, SECTOR_LIST, NSE_UNIVERSE
from utils.orb_engine import ORBEngine, market_phase, ist_now, is_market_open
from utils.charts import (
    orb_candlestick, status_donut, rsi_histogram,
    sector_bar, orb_scatter, alert_timeline,
)

# ── Streamlit page config ────────────────────────────────────
st.set_page_config(
    page_title  = "NSE ORB Terminal",
    page_icon   = "📡",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

IST = pytz.timezone("Asia/Kolkata")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@500;700&family=Oxanium:wght@700;800&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    background-color: #040d14 !important;
    color: #c8dbe8 !important;
    font-family: 'Rajdhani', sans-serif !important;
}
.stApp { background-color: #040d14; }
section[data-testid="stSidebar"] { background-color: #071520 !important; border-right: 1px solid #1a3a52; }

/* ── Header ── */
.orb-header {
    background: linear-gradient(90deg,#041522,#071d2e,#041522);
    border-bottom: 2px solid #00e5ff;
    padding: 14px 24px;
    display: flex; align-items:center; justify-content:space-between;
    box-shadow: 0 0 30px rgba(0,229,255,0.08);
    margin-bottom: 12px;
}
.orb-logo { font-family:'Oxanium',sans-serif; font-size:26px; font-weight:800;
            color:#00e5ff; letter-spacing:3px; text-shadow: 0 0 20px rgba(0,229,255,0.5); }
.orb-sub  { font-family:'Share Tech Mono',monospace; font-size:10px;
            color:#7fa8c2; letter-spacing:2px; }
.orb-clock { font-family:'Share Tech Mono',monospace; font-size:28px;
             color:#00e5ff; text-shadow: 0 0 15px rgba(0,229,255,0.5);
             text-align:center; }
.orb-date  { font-family:'Share Tech Mono',monospace; font-size:11px;
             color:#7fa8c2; text-align:center; }

/* ── Status badges ── */
.badge {
    display:inline-block; padding:3px 10px; border-radius:3px;
    font-family:'Share Tech Mono',monospace; font-size:11px;
    font-weight:700; letter-spacing:1px; border:1px solid;
}
.badge-breakout  { background:rgba(0,230,118,0.1); border-color:#00e676; color:#00e676; }
.badge-breakdown { background:rgba(255,23,68,0.1);  border-color:#ff1744; color:#ff1744; }
.badge-watching  { background:rgba(255,204,2,0.1);  border-color:#ffcc02; color:#ffcc02; }
.badge-orbset    { background:rgba(122,170,194,0.1);border-color:#7fa8c2; color:#7fa8c2; }

/* ── Metric cards ── */
.metric-card {
    background:#071520; border:1px solid #1a3a52; border-radius:6px;
    padding:14px 16px; text-align:center;
}
.metric-val  { font-family:'Oxanium',sans-serif; font-size:28px; font-weight:700; line-height:1; }
.metric-label{ font-family:'Share Tech Mono',monospace; font-size:10px;
               color:#7fa8c2; letter-spacing:1px; text-transform:uppercase; margin-top:4px; }

/* ── Alert ticker ── */
.alert-ticker {
    background: linear-gradient(90deg,#0d0014,#1a0020,#0d0014);
    border-top:1px solid rgba(255,107,53,0.4);
    border-bottom:1px solid rgba(255,107,53,0.4);
    padding:7px 16px; font-family:'Share Tech Mono',monospace;
    font-size:12px; color:#ffcc02; overflow:hidden;
    white-space:nowrap; margin-bottom:10px;
}

/* ── Phase bar ── */
.phase-bar {
    display:flex; gap:0; background:#0a1e2e;
    border:1px solid #1a3a52; border-radius:5px;
    overflow:hidden; margin-bottom:10px;
}
.phase-item {
    flex:1; text-align:center; padding:8px 4px;
    font-family:'Share Tech Mono',monospace; font-size:10px;
    letter-spacing:1px; color:#7fa8c2;
    border-right:1px solid #1a3a52;
}
.phase-item.active { background:rgba(0,229,255,0.08); color:#00e5ff; }
.phase-item.done   { color:#00e676; }
.phase-item:last-child { border-right:none; }

/* ── Table ── */
.stock-table th {
    font-family:'Oxanium',sans-serif !important;
    font-size:11px !important; letter-spacing:1px !important;
    color:#00e5ff !important; background:#0d2235 !important;
    text-transform:uppercase !important;
}
.stock-table td {
    font-family:'Share Tech Mono',monospace !important;
    font-size:12px !important; border-bottom:1px solid rgba(26,58,82,0.5) !important;
}

/* ── Alert card ── */
.alert-card {
    background:#0d2235; border-radius:5px; padding:10px 12px;
    margin-bottom:8px; border-left:3px solid;
}
.alert-card.bull { border-left-color:#00e676; }
.alert-card.bear { border-left-color:#ff1744; }
.alert-sym   { font-family:'Oxanium',sans-serif; font-weight:700; font-size:15px; color:#fff; }
.alert-time  { font-family:'Share Tech Mono',monospace; font-size:10px; color:#7fa8c2; float:right; }
.alert-msg   { font-family:'Share Tech Mono',monospace; font-size:11px; color:#c8dbe8; margin-top:3px; }
.alert-price { font-family:'Oxanium',sans-serif; font-size:16px; font-weight:700; }

/* ── Sidebar ── */
.sidebar-section {
    background:#0a1e2e; border:1px solid #1a3a52; border-radius:6px;
    padding:12px; margin-bottom:10px;
}
.sidebar-title {
    font-family:'Oxanium',sans-serif; font-size:12px; font-weight:700;
    color:#00e5ff; letter-spacing:2px; text-transform:uppercase;
    margin-bottom:8px;
}

/* ── Streamlit widget overrides ── */
.stTextInput input, .stNumberInput input, .stSelectbox div {
    background:#0a1e2e !important; border:1px solid #1a3a52 !important;
    color:#c8dbe8 !important; font-family:'Share Tech Mono',monospace !important;
}
.stButton>button {
    background:transparent !important; border:1px solid #00e5ff !important;
    color:#00e5ff !important; font-family:'Rajdhani',sans-serif !important;
    font-weight:700 !important; letter-spacing:1px !important;
    text-transform:uppercase !important; transition:all 0.2s !important;
}
.stButton>button:hover { background:rgba(0,229,255,0.1) !important; }
div[data-testid="stMetricValue"] {
    font-family:'Oxanium',sans-serif !important;
    color:#00e5ff !important;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "engine":        None,
        "client":        None,
        "streamer":      None,
        "scan_done":     False,
        "orb_done":      False,
        "rsi_done":      False,
        "api_key":       "",
        "data_source":   "REST Poll",
        "cmp_min":       500,
        "refresh_sec":   30,
        "rsi_period":    14,
        "ws_status":     "idle",
        "last_refresh":  None,
        "scan_progress": 0,
        "scan_msg":      "",
        "alert_sound":   True,
        "selected_sym":  None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─────────────────────────────────────────────────────────────
# Auto-refresh  (only during market hours)
# ─────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    if st.session_state.scan_done and is_market_open():
        refresh_ms = max(10_000, st.session_state.refresh_sec * 1000)
        st_autorefresh(interval=refresh_ms, key="auto_refresh")
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────
# Helper: get or create ORBEngine
# ─────────────────────────────────────────────────────────────
def get_engine() -> ORBEngine:
    if st.session_state.engine is None:
        st.session_state.engine = ORBEngine()
    return st.session_state.engine


def get_client() -> TwelveDataClient | None:
    if st.session_state.api_key and st.session_state.client is None:
        st.session_state.client = TwelveDataClient(st.session_state.api_key)
    return st.session_state.client


# ─────────────────────────────────────────────────────────────
# Phase bar HTML
# ─────────────────────────────────────────────────────────────
def phase_bar_html(phase: str) -> str:
    phases = [
        ("pre_market",   "PRE 9:00"),
        ("pre_open",     "PRE-OPEN 9:00"),
        ("orb_window",   "ORB 9:15"),
        ("market_open",  "MONITOR 9:30"),
        ("closed",       "CLOSE 3:30"),
    ]
    ordered = ["pre_market","pre_open","orb_window","market_open","closed"]
    try:
        active_idx = ordered.index(phase)
    except ValueError:
        active_idx = -1

    items = []
    for i, (key, label) in enumerate(phases):
        cls = "active" if key == phase else ("done" if i < active_idx else "")
        dot = "●" if cls == "active" else ("✓" if cls == "done" else "○")
        items.append(f'<div class="phase-item {cls}">{dot} {label}</div>')
    return f'<div class="phase-bar">{"".join(items)}</div>'


# ─────────────────────────────────────────────────────────────
# Market status badge
# ─────────────────────────────────────────────────────────────
def market_badge_html(phase: str) -> str:
    cfg = {
        "market_open":  ("🟢", "LIVE", "#00e676"),
        "orb_window":   ("🟡", "ORB WINDOW", "#ffcc02"),
        "pre_open":     ("🟡", "PRE-OPEN", "#ffcc02"),
        "pre_market":   ("⚪", "PRE-MARKET", "#7fa8c2"),
        "closed":       ("🔴", "CLOSED", "#ff1744"),
    }
    icon, text, color = cfg.get(phase, ("⚪","—","#7fa8c2"))
    return (f'<span style="background:rgba(0,0,0,0.3);border:1px solid {color};'
            f'border-radius:4px;padding:4px 12px;font-family:Share Tech Mono,monospace;'
            f'font-size:12px;font-weight:700;letter-spacing:2px;color:{color}">'
            f'{icon} {text}</span>')


# ─────────────────────────────────────────────────────────────
# Status badge HTML
# ─────────────────────────────────────────────────────────────
def status_badge(status: str) -> str:
    cfg = {
        "BREAKOUT":      ("▲ BREAKOUT",  "breakout"),
        "BREAKDOWN":     ("▼ BREAKDOWN", "breakdown"),
        "WATCHING_HIGH": ("◎ NEAR HIGH", "watching"),
        "WATCHING_LOW":  ("◎ NEAR LOW",  "watching"),
        "ORB_SET":       ("▷ ORB SET",   "orbset"),
    }
    text, cls = cfg.get(status, (status, "orbset"))
    return f'<span class="badge badge-{cls}">{text}</span>'


# ─────────────────────────────────────────────────────────────
# RSI sparkline HTML (inline bar)
# ─────────────────────────────────────────────────────────────
def rsi_html(val: float) -> str:
    pct = min(100, max(0, val))
    if val >= 70:   color = "#00e676"
    elif val <= 30: color = "#ff1744"
    else:           color = "#7fa8c2"
    bar = (f'<div style="display:flex;align-items:center;gap:6px">'
           f'<div style="width:50px;height:5px;background:#1a3a52;border-radius:3px;overflow:hidden">'
           f'<div style="width:{pct}%;height:100%;background:{color};border-radius:3px"></div></div>'
           f'<span style="color:{color};font-size:12px;font-weight:700">{val:.1f}</span></div>')
    return bar


# ─────────────────────────────────────────────────────────────
# Scan workflow  (runs in main thread with progress feedback)
# ─────────────────────────────────────────────────────────────
def run_scan():
    api_key     = st.session_state.api_key.strip()
    cmp_min     = st.session_state.cmp_min
    data_source = st.session_state.data_source
    rsi_period  = st.session_state.rsi_period
    use_live    = bool(api_key) and data_source != "Demo Mode"

    engine = get_engine()
    engine.reset()

    universe = get_universe(cmp_min)
    if not universe:
        st.error("No stocks found for CMP filter. Reduce CMP minimum.")
        return

    engine.init_stocks(universe)
    symbols = [e[0] for e in universe]

    prog_bar = st.progress(0, text="Initialising…")

    if use_live:
        client = TwelveDataClient(api_key)
        st.session_state.client = client

        # ── Step 1 / 3 : Live quotes ────────────────────────
        prog_bar.progress(5, text=f"Step 1/3 — Fetching live quotes for {len(symbols)} stocks…")
        quotes = client.get_quotes(symbols)
        if quotes:
            engine.update_quotes(quotes)
            # Re-filter by actual live CMP
            live_df = engine.get_df()
            below   = live_df[live_df["cmp"] < cmp_min]["symbol"].tolist()
            if below:
                with engine._lock:
                    engine._df = engine._df[engine._df["cmp"] >= cmp_min].reset_index(drop=True)
        prog_bar.progress(35, text=f"Quotes loaded — {len(engine.get_df())} stocks pass CMP > ₹{cmp_min}")

        # ── Step 2 / 3 : ORB candles ────────────────────────
        phase = market_phase()
        if phase in ("orb_window", "market_open"):
            prog_bar.progress(36, text="Step 2/3 — Capturing ORB candles (9:15 AM candle)…")
            syms_for_orb = engine.get_df()["symbol"].tolist()

            def orb_progress(done, total):
                pct = 36 + int(done / total * 34)
                prog_bar.progress(pct, text=f"ORB candles: {done}/{total}")

            candles = client.get_orb_candles_batch(syms_for_orb, progress_cb=orb_progress)
            engine.apply_orb_candles(candles)
            st.session_state.orb_done = True
        else:
            # Outside ORB window — infer placeholder ORB from open ± spread
            _inject_placeholder_orb(engine)
            prog_bar.progress(70, text="ORB window not active — using inferred ranges")

        # ── Step 3 / 3 : RSI ────────────────────────────────
        prog_bar.progress(71, text="Step 3/3 — Fetching RSI (daily)…")
        syms_for_rsi = engine.get_df()["symbol"].tolist()

        def rsi_progress(done, total):
            pct = 71 + int(done / total * 24)
            prog_bar.progress(pct, text=f"RSI: {done}/{total}")

        rsi_map = client.get_rsi_batch(
            syms_for_rsi, period=rsi_period, max_symbols=40,
            progress_cb=rsi_progress,
        )
        engine.apply_rsi(rsi_map)
        st.session_state.rsi_done = True

        prog_bar.progress(96, text="Setting up data feed…")

        # ── Connect WebSocket or REST polling ───────────────
        if data_source == "Live (WebSocket)":
            _start_websocket(symbols)
        # REST polling happens on each auto-refresh rerun

    else:
        # ── Demo mode ───────────────────────────────────────
        prog_bar.progress(20, text="Loading demo data…")
        _inject_demo_data(engine)
        prog_bar.progress(85, text="Demo data loaded")
        time.sleep(0.3)

    prog_bar.progress(100, text="Scan complete ✓")
    time.sleep(0.4)
    prog_bar.empty()

    engine.scan_ts = ist_now()
    st.session_state.scan_done    = True
    st.session_state.last_refresh = ist_now()


def _inject_placeholder_orb(engine: ORBEngine):
    """Infer ORB from open price when outside market hours."""
    import random
    candles = {}
    for sym in engine.get_df()["symbol"].tolist():
        row  = engine.get_stock(sym)
        opn  = float(row["open"])
        rng  = opn * (0.003 + random.random() * 0.009)
        candles[sym] = {
            "open":  opn,
            "high":  round(opn + rng * (0.4 + random.random() * 0.6), 2),
            "low":   round(opn - rng * (0.4 + random.random() * 0.6), 2),
            "close": opn,
        }
    engine.apply_orb_candles(candles)
    engine.orb_ts = ist_now()


def _inject_demo_data(engine: ORBEngine):
    """Populate engine with realistic demo prices + ORB + RSI."""
    import random
    quotes  = {}
    candles = {}
    rsi_map = {}

    for sym in engine.get_df()["symbol"].tolist():
        row   = engine.get_stock(sym)
        base  = float(row["cmp"])
        opn   = round(base * (1 + (random.random() - 0.49) * 0.015), 2)
        rng   = opn * (0.003 + random.random() * 0.012)
        high  = round(opn + rng * (0.5 + random.random() * 0.5), 2)
        low   = round(opn - rng * (0.5 + random.random() * 0.5), 2)

        t = random.random()
        if t > 0.78:   cmp = round(high * (1 + 0.001 + random.random() * 0.010), 2)
        elif t < 0.22: cmp = round(low  * (1 - 0.001 - random.random() * 0.010), 2)
        elif t > 0.65: cmp = round(high * (1 - random.random() * 0.003), 2)
        elif t < 0.35: cmp = round(low  * (1 + random.random() * 0.003), 2)
        else:          cmp = round(low  + random.random() * (high - low), 2)

        chg = round((cmp - opn) / opn * 100, 2)
        quotes[sym]  = {"close": cmp, "open": opn, "percent_change": chg}
        candles[sym] = {"open": opn, "high": high, "low": low, "close": cmp}

        if   cmp > high: rsi = round(55 + random.random() * 20, 1)
        elif cmp < low:  rsi = round(25 + random.random() * 20, 1)
        else:            rsi = round(35 + random.random() * 30, 1)
        rsi_map[sym] = rsi

    engine.update_quotes(quotes)
    engine.apply_orb_candles(candles)
    engine.apply_rsi(rsi_map)
    engine.scan_ts = ist_now()
    engine.orb_ts  = ist_now()


def _start_websocket(symbols: list[str]):
    """Launch WS streamer in daemon thread, writing ticks to engine."""
    engine = get_engine()

    def on_price(sym, price, ts):
        engine.update_price(sym, price)

    def on_status(s):
        st.session_state.ws_status = s

    streamer = TDWebSocketStreamer(
        api_key     = st.session_state.api_key,
        on_price_cb = on_price,
        on_status_cb= on_status,
    )
    streamer.set_symbols(symbols)
    streamer.start()
    st.session_state.streamer = streamer


def rest_refresh():
    """Called on each auto-refresh rerun to poll fresh quotes."""
    if not st.session_state.scan_done:
        return
    if st.session_state.data_source != "REST Poll":
        return
    client = get_client()
    if not client:
        return
    engine = get_engine()
    syms   = engine.get_df()["symbol"].tolist()
    if not syms:
        return
    quotes = client.get_quotes(syms)
    if quotes:
        engine.update_quotes(quotes)
    st.session_state.last_refresh = ist_now()


# ─────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown('<div class="orb-logo" style="font-size:20px;margin-bottom:4px">📡 NSE ORB TERMINAL</div>', unsafe_allow_html=True)
        st.markdown('<div class="orb-sub">Opening Range Breakout Scanner</div>', unsafe_allow_html=True)
        st.markdown("---")

        # ── API Key ─────────────────────────────────────────
        st.markdown('<div class="sidebar-title">🔑 Twelve Data API</div>', unsafe_allow_html=True)
        api_key = st.text_input(
            "API Key", type="password",
            value=st.session_state.api_key,
            placeholder="Paste your Twelve Data key…",
            help="Get a free key at twelvedata.com"
        )
        st.session_state.api_key = api_key

        col1, col2 = st.columns(2)
        with col1:
            if st.button("TEST", use_container_width=True):
                if api_key:
                    with st.spinner("Testing…"):
                        c = TwelveDataClient(api_key)
                        ok, msg = c.test_connection()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("Enter API key first")
        with col2:
            if st.button("SAVE", use_container_width=True):
                st.success("Key saved to session")

        st.caption("Free plan: 800 credits/day · 8 req/min")
        st.markdown("---")

        # ── Data source ─────────────────────────────────────
        st.markdown('<div class="sidebar-title">📡 Data Source</div>', unsafe_allow_html=True)
        data_source = st.selectbox(
            "Mode",
            ["Live (WebSocket)", "REST Poll", "Demo Mode"],
            index=["Live (WebSocket)", "REST Poll", "Demo Mode"].index(
                st.session_state.data_source),
            help="WebSocket=real-time ticks · REST=periodic poll · Demo=simulated",
        )
        st.session_state.data_source = data_source

        if data_source == "Live (WebSocket)" and st.session_state.ws_status != "idle":
            color = "#00e676" if st.session_state.ws_status == "connected" else "#ffcc02"
            st.markdown(
                f'<span style="color:{color};font-family:Share Tech Mono,monospace;font-size:11px">'
                f'● WS: {st.session_state.ws_status.upper()}</span>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Scan config ──────────────────────────────────────
        st.markdown('<div class="sidebar-title">⚙ Scan Config</div>', unsafe_allow_html=True)
        cmp_min = st.number_input(
            "Min CMP (₹)", min_value=100, max_value=200000,
            value=st.session_state.cmp_min, step=50,
            help="Only include stocks with CMP > this value",
        )
        st.session_state.cmp_min = cmp_min

        rsi_period = st.number_input(
            "RSI Period (days)", min_value=5, max_value=30,
            value=st.session_state.rsi_period, step=1,
        )
        st.session_state.rsi_period = rsi_period

        refresh_sec = st.number_input(
            "Auto-refresh (seconds)", min_value=10, max_value=300,
            value=st.session_state.refresh_sec, step=5,
        )
        st.session_state.refresh_sec = refresh_sec

        st.markdown("---")

        # ── Scan button ──────────────────────────────────────
        mode_label = "🔴 DEMO" if data_source == "Demo Mode" else "🟢 LIVE"
        if st.button(f"▶ SCAN / CONNECT  {mode_label}", use_container_width=True, type="primary"):
            run_scan()
            st.rerun()

        if st.session_state.scan_done:
            if st.button("🔄 REFRESH QUOTES", use_container_width=True):
                if st.session_state.data_source == "REST Poll":
                    rest_refresh()
                else:
                    _inject_demo_data(get_engine())
                st.rerun()
            if st.button("✕ CLEAR ALERTS", use_container_width=True):
                get_engine().clear_alerts()
                st.rerun()
            if st.button("⏹ DISCONNECT", use_container_width=True):
                s = st.session_state.streamer
                if s:
                    s.stop()
                    st.session_state.streamer = None
                st.session_state.ws_status = "idle"
                st.rerun()

        st.markdown("---")

        # ── Scan metadata ────────────────────────────────────
        if st.session_state.scan_done:
            e = get_engine()
            st.markdown('<div class="sidebar-title">📊 Session Info</div>', unsafe_allow_html=True)
            if e.scan_ts:
                st.caption(f"Scanned: {e.scan_ts.strftime('%H:%M:%S IST')}")
            if e.orb_ts:
                st.caption(f"ORB locked: {e.orb_ts.strftime('%H:%M:%S IST')}")
            if st.session_state.last_refresh:
                st.caption(f"Last refresh: {st.session_state.last_refresh.strftime('%H:%M:%S IST')}")
            stats = e.get_stats()
            st.caption(f"Stocks loaded: {stats['total']}")
            st.caption(f"ORB captured: {stats['orb_captured']}")


# ─────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────
def render_header():
    now   = ist_now()
    phase = market_phase(now)

    col_logo, col_clock, col_status = st.columns([3, 2, 2])
    with col_logo:
        st.markdown(
            '<div class="orb-logo">NSE ORB TERMINAL</div>'
            '<div class="orb-sub">OPENING RANGE BREAKOUT SCANNER — TWELVE DATA EDITION</div>',
            unsafe_allow_html=True,
        )
    with col_clock:
        st.markdown(
            f'<div class="orb-clock">{now.strftime("%H:%M:%S")}</div>'
            f'<div class="orb-date">{now.strftime("%a %d %b %Y")} — IST</div>',
            unsafe_allow_html=True,
        )
    with col_status:
        st.markdown(market_badge_html(phase), unsafe_allow_html=True)
        if st.session_state.scan_done:
            src = st.session_state.data_source
            src_color = "#00e5ff" if "Live" in src else "#ffcc02" if "REST" in src else "#7fa8c2"
            st.markdown(
                f'<span style="font-family:Share Tech Mono,monospace;font-size:10px;color:{src_color}">'
                f'DATA: {src.upper()}</span>',
                unsafe_allow_html=True,
            )

    st.markdown(phase_bar_html(phase), unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Stats strip
# ─────────────────────────────────────────────────────────────
def render_stats(stats: dict):
    items = [
        ("SCANNED",    str(len(NSE_UNIVERSE)),                  "#7fa8c2"),
        ("CMP > ₹500", str(stats["total"]),                     "#00e5ff"),
        ("ORB SET",    str(stats["orb_captured"]),               "#00e5ff"),
        ("BREAKOUTS ↑",str(stats["breakouts"]),                  "#00e676"),
        ("BREAKDOWNS ↓",str(stats["breakdowns"]),                "#ff1744"),
        ("WATCHING",   str(stats["watching"]),                   "#ffcc02"),
        ("ALERTS",     str(stats["alerts"]),                     "#ff6b35"),
    ]
    cols = st.columns(len(items))
    for col, (label, val, color) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-val" style="color:{color}">{val}</div>'
                f'<div class="metric-label">{label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────
# Alert ticker strip
# ─────────────────────────────────────────────────────────────
def render_ticker(alerts: list[dict]):
    if not alerts:
        msg = "No alerts yet — ORB breakouts and breakdowns will appear here during market hours (9:30–15:30 IST)"
    else:
        parts = []
        for a in alerts[-20:]:
            arrow = "▲" if a["type"] == "BREAKOUT" else "▼"
            parts.append(f"{arrow} {a['symbol']} {a['type']} @ ₹{a['cmp']:.2f}  [{a['time']}]")
        msg = "   ⬥   ".join(parts)
    st.markdown(f'<div class="alert-ticker">⚡ LIVE ALERTS   {msg}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Main stock table
# ─────────────────────────────────────────────────────────────
def render_table(df: pd.DataFrame, filters: dict):
    if df.empty:
        st.info("No stocks loaded. Click **SCAN / CONNECT** in the sidebar.")
        return

    # Apply filters
    fdf = df.copy()
    if filters["search"]:
        fdf = fdf[fdf["symbol"].str.contains(filters["search"].upper(), na=False)]
    if filters["status"] != "All":
        status_map = {
            "Breakout":  "BREAKOUT",
            "Breakdown": "BREAKDOWN",
            "Watching":  ["WATCHING_HIGH","WATCHING_LOW"],
            "ORB Set":   "ORB_SET",
        }
        filt = status_map.get(filters["status"])
        if isinstance(filt, list):
            fdf = fdf[fdf["status"].isin(filt)]
        elif filt:
            fdf = fdf[fdf["status"] == filt]
    if filters["sector"] != "All":
        fdf = fdf[fdf["sector"] == filters["sector"]]
    if filters["rsi_zone"] == "Overbought >70":
        fdf = fdf[fdf["rsi"] > 70]
    elif filters["rsi_zone"] == "Oversold <30":
        fdf = fdf[fdf["rsi"] < 30]
    elif filters["rsi_zone"] == "Neutral 40-60":
        fdf = fdf[(fdf["rsi"] >= 40) & (fdf["rsi"] <= 60)]

    # Sort
    sort_map = {
        "Symbol":    ("symbol", True),
        "CMP ↓":     ("cmp", False),
        "Change %":  ("change_pct", False),
        "RSI":       ("rsi", False),
        "ORB Range": ("orb_range_pct", False),
    }
    scol, sasc = sort_map.get(filters["sort"], ("symbol", True))
    fdf = fdf.sort_values(scol, ascending=sasc)

    st.caption(f"Showing **{len(fdf)}** of **{len(df)}** stocks")

    # Build display DataFrame
    display_rows = []
    for _, row in fdf.iterrows():
        cmp_color   = "#00e676" if row["change_pct"] >= 0 else "#ff1744"
        chg_prefix  = "+" if row["change_pct"] >= 0 else ""
        orb_h_str   = f"₹{row['orb_high']:,.2f}" if row["orb_high"] > 0 else "—"
        orb_l_str   = f"₹{row['orb_low']:,.2f}"  if row["orb_low"]  > 0 else "—"
        orb_r_str   = f"{row['orb_range_pct']:.2f}%" if row["orb_captured"] else "—"
        dist_h_str  = f"{row['dist_to_high_pct']:.2f}%" if row["orb_captured"] else "—"
        dist_l_str  = f"{row['dist_to_low_pct']:.2f}%"  if row["orb_captured"] else "—"

        display_rows.append({
            "Symbol":    row["symbol"],
            "Sector":    row["sector"],
            "CMP ₹":     f"₹{row['cmp']:,.2f}",
            "Chg %":     f"{chg_prefix}{row['change_pct']:.2f}%",
            "ORB High":  orb_h_str,
            "ORB Low":   orb_l_str,
            "Range %":   orb_r_str,
            "→High":     dist_h_str,
            "→Low":      dist_l_str,
            "RSI(D)":    f"{row['rsi']:.1f}",
            "Status":    row["status"],
            "Alert":     row["alert_time"] if row["alert_time"] else "—",
        })

    display_df = pd.DataFrame(display_rows)

    # Colour-map status column
    def highlight_row(row):
        styles = [""] * len(row)
        s = row["Status"]
        if s == "BREAKOUT":
            styles = [f"color: #00e676; background: rgba(0,230,118,0.05)"] * len(row)
        elif s == "BREAKDOWN":
            styles = [f"color: #ff1744; background: rgba(255,23,68,0.05)"] * len(row)
        elif "WATCHING" in s:
            styles = [f"color: #ffcc02; background: rgba(255,204,2,0.03)"] * len(row)
        return styles

    styled = (
        display_df.style
        .apply(highlight_row, axis=1)
        .set_properties(**{
            "font-family": "Share Tech Mono, monospace",
            "font-size":   "12px",
        })
        .set_table_styles([{
            "selector": "th",
            "props": [
                ("background", "#0d2235"),
                ("color", "#00e5ff"),
                ("font-family", "Oxanium, sans-serif"),
                ("font-size", "11px"),
                ("letter-spacing", "1px"),
                ("text-transform", "uppercase"),
            ]
        }])
        .hide(axis="index")
    )
    st.dataframe(
        styled,
        use_container_width=True,
        height=520,
    )

    return fdf


# ─────────────────────────────────────────────────────────────
# Alert log panel
# ─────────────────────────────────────────────────────────────
def render_alerts(alerts: list[dict]):
    st.markdown(
        f'<div style="font-family:Oxanium,sans-serif;font-weight:700;font-size:13px;'
        f'color:#00e5ff;letter-spacing:2px;margin-bottom:8px">'
        f'⚡ ALERT LOG  <span style="background:#00e5ff;color:#040d14;border-radius:10px;'
        f'padding:2px 8px;font-size:11px">{len(alerts)}</span></div>',
        unsafe_allow_html=True,
    )
    if not alerts:
        st.markdown(
            '<div style="color:#7fa8c2;font-family:Share Tech Mono,monospace;'
            'font-size:12px;text-align:center;padding:24px 0">'
            'No alerts yet.<br>Alerts fire when CMP<br>breaks ORB High or Low.</div>',
            unsafe_allow_html=True,
        )
        return

    for a in reversed(alerts[-30:]):
        is_bull = a["type"] == "BREAKOUT"
        color   = "#00e676" if is_bull else "#ff1744"
        arrow   = "▲" if is_bull else "▼"
        ref_lbl = "ORB HIGH" if is_bull else "ORB LOW"
        chg_pfx = "+" if a["change_pct"] >= 0 else ""

        st.markdown(f"""
        <div class="alert-card {'bull' if is_bull else 'bear'}">
          <span class="alert-sym">{a['symbol']}</span>
          <span class="alert-time">{a['time']}</span>
          <div class="alert-msg">{arrow} {a['type']} — {ref_lbl} ₹{a['orb_ref']:.2f} broken</div>
          <div style="display:flex;justify-content:space-between;margin-top:4px">
            <span class="alert-price" style="color:{color}">₹{a['cmp']:.2f}</span>
            <span style="font-family:Share Tech Mono,monospace;font-size:12px;color:{color}">
              {chg_pfx}{a['change_pct']:.2f}%</span>
          </div>
          <div style="font-family:Share Tech Mono,monospace;font-size:10px;color:#7fa8c2;margin-top:2px">
            RSI {a['rsi']:.1f} · {a['sector']}</div>
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# Filters row
# ─────────────────────────────────────────────────────────────
def render_filters() -> dict:
    c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1.5])
    with c1:
        search = st.text_input("Search symbol", placeholder="e.g. RELIANCE", label_visibility="collapsed")
    with c2:
        status = st.selectbox("Status", ["All","Breakout","Breakdown","Watching","ORB Set"], label_visibility="collapsed")
    with c3:
        sector = st.selectbox("Sector", ["All"] + SECTOR_LIST, label_visibility="collapsed")
    with c4:
        rsi_zone = st.selectbox("RSI Zone", ["All","Overbought >70","Oversold <30","Neutral 40-60"], label_visibility="collapsed")
    with c5:
        sort = st.selectbox("Sort by", ["Symbol","CMP ↓","Change %","RSI","ORB Range"], label_visibility="collapsed")
    return dict(search=search, status=status, sector=sector, rsi_zone=rsi_zone, sort=sort)


# ─────────────────────────────────────────────────────────────
# Stock detail expander (charts + data)
# ─────────────────────────────────────────────────────────────
def render_stock_detail(symbol: str, engine: ORBEngine):
    stock = engine.get_stock(symbol)
    if not stock:
        return
    with st.expander(f"📈 Detail: {symbol}", expanded=True):
        col_d, col_c = st.columns([1, 2])
        with col_d:
            color = "#00e676" if stock["change_pct"] >= 0 else "#ff1744"
            pfx   = "+" if stock["change_pct"] >= 0 else ""
            items = [
                ("CMP",       f"₹{stock['cmp']:,.2f}",      color),
                ("Change",    f"{pfx}{stock['change_pct']:.2f}%", color),
                ("Open",      f"₹{stock['open']:,.2f}",      "#c8dbe8"),
                ("ORB High",  f"₹{stock['orb_high']:,.2f}",  "#00e676"),
                ("ORB Low",   f"₹{stock['orb_low']:,.2f}",   "#ff1744"),
                ("ORB Range", f"{stock['orb_range_pct']:.2f}%","#00e5ff"),
                ("RSI(14D)",  f"{stock['rsi']:.1f}",
                 "#00e676" if stock["rsi"]>=70 else "#ff1744" if stock["rsi"]<=30 else "#7fa8c2"),
                ("Status",    stock["status"],               "#ffcc02"),
                ("→ High",    f"{stock['dist_to_high_pct']:.2f}%", "#c8dbe8"),
                ("→ Low",     f"{stock['dist_to_low_pct']:.2f}%",  "#c8dbe8"),
                ("Sector",    stock["sector"],               "#7fa8c2"),
            ]
            for lbl, val, col in items:
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'border-bottom:1px solid #1a3a52;padding:4px 0;'
                    f'font-family:Share Tech Mono,monospace;font-size:12px">'
                    f'<span style="color:#7fa8c2">{lbl}</span>'
                    f'<span style="color:{col}">{val}</span></div>',
                    unsafe_allow_html=True,
                )

        with col_c:
            client = get_client()
            if client and st.session_state.data_source != "Demo Mode":
                with st.spinner("Loading intraday chart…"):
                    bars = client.get_intraday(symbol, interval="5min", bars=78)
            else:
                bars = []

            if bars:
                fig = orb_candlestick(
                    candles  = bars,
                    orb_high = float(stock["orb_high"]),
                    orb_low  = float(stock["orb_low"]),
                    symbol   = symbol,
                    height   = 340,
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Intraday chart requires a live API connection.")


# ─────────────────────────────────────────────────────────────
# Analytics tab
# ─────────────────────────────────────────────────────────────
def render_analytics(df: pd.DataFrame, alerts: list[dict]):
    c1, c2 = st.columns([1, 2])
    with c1:
        stats = get_engine().get_stats()
        st.plotly_chart(status_donut(stats), use_container_width=True, config={"displayModeBar": False})
        if not df.empty:
            st.plotly_chart(rsi_histogram(df), use_container_width=True, config={"displayModeBar": False})
    with c2:
        if not df.empty:
            st.plotly_chart(orb_scatter(df), use_container_width=True, config={"displayModeBar": False})
            st.plotly_chart(sector_bar(df), use_container_width=True, config={"displayModeBar": False})

    if alerts:
        st.plotly_chart(alert_timeline(alerts), use_container_width=True, config={"displayModeBar": False})


# ─────────────────────────────────────────────────────────────
# Main layout
# ─────────────────────────────────────────────────────────────
def main():
    # Trigger REST refresh on each auto-rerun
    if st.session_state.data_source == "REST Poll":
        rest_refresh()

    render_sidebar()
    render_header()

    engine = get_engine()

    if not st.session_state.scan_done:
        # ── Welcome screen ───────────────────────────────────
        st.markdown("""
        <div style="background:#071520;border:1px solid #1a3a52;border-radius:8px;
                    padding:32px;text-align:center;margin-top:40px">
          <div style="font-family:Oxanium,sans-serif;font-size:24px;font-weight:800;
                      color:#00e5ff;letter-spacing:3px;margin-bottom:12px">
            NSE ORB TERMINAL
          </div>
          <div style="font-family:Share Tech Mono,monospace;font-size:13px;
                      color:#7fa8c2;line-height:1.8;max-width:600px;margin:0 auto">
            <b style="color:#c8dbe8">How to start:</b><br>
            1. Enter your <b style="color:#00e5ff">Twelve Data API key</b> in the sidebar
               &nbsp;→&nbsp; <a href="https://twelvedata.com" target="_blank" 
               style="color:#00e5ff">twelvedata.com</a><br>
            2. Choose <b>Live (WebSocket)</b> for real-time ticks or <b>REST Poll</b> 
               for periodic refresh<br>
            3. Set your <b>CMP minimum</b> (default ₹500) and click 
               <b style="color:#00e5ff">▶ SCAN / CONNECT</b><br>
            4. ORB range is captured from the <b>9:15 AM 15-min candle</b><br>
            5. Breakout / Breakdown <b>alerts fire instantly</b> during 9:30–15:30 IST<br><br>
            No API key? Select <b>Demo Mode</b> to explore with simulated data.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    df     = engine.get_df()
    stats  = engine.get_stats()
    alerts = engine.get_alerts()

    render_stats(stats)
    render_ticker(alerts)

    # ── Main tabs ────────────────────────────────────────────
    tab_scan, tab_alerts, tab_analytics = st.tabs(["📊 Scanner", "⚡ Alerts", "📈 Analytics"])

    with tab_scan:
        filters = render_filters()
        left_col, right_col = st.columns([3.5, 1])
        with left_col:
            filtered_df = render_table(df, filters)
        with right_col:
            render_alerts(alerts)

        # Stock detail click — symbol search
        if filtered_df is not None and not filtered_df.empty:
            st.markdown("---")
            detail_sym = st.selectbox(
                "🔍 View stock detail",
                ["— select —"] + filtered_df["symbol"].tolist(),
                label_visibility="visible",
            )
            if detail_sym and detail_sym != "— select —":
                render_stock_detail(detail_sym, engine)

    with tab_alerts:
        if not alerts:
            st.info("No alerts yet. Alerts fire when CMP breaks ORB High or Low during market hours.")
        else:
            alert_df = pd.DataFrame(alerts)
            st.dataframe(
                alert_df[["time","symbol","sector","type","cmp","orb_ref","change_pct","rsi"]]
                .rename(columns={
                    "time":"Time","symbol":"Symbol","sector":"Sector",
                    "type":"Type","cmp":"CMP ₹","orb_ref":"ORB Ref ₹",
                    "change_pct":"Chg %","rsi":"RSI",
                }),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "⬇ Export Alerts CSV",
                data=alert_df.to_csv(index=False),
                file_name=f"nse_orb_alerts_{ist_now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )

    with tab_analytics:
        render_analytics(df, alerts)


if __name__ == "__main__":
    main()
