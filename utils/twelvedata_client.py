"""
twelvedata_client.py
────────────────────
Twelve Data API wrapper for NSE ORB Terminal.
Handles: quotes, time_series, RSI, WebSocket streaming.

Docs: https://twelvedata.com/docs
NSE symbol format : "RELIANCE:NSE"
Exchange           : NSE  (National Stock Exchange of India)
"""

import time
import logging
import threading
import requests
import websocket
import json
from typing import Optional, Callable
from datetime import datetime
import pytz

log = logging.getLogger(__name__)

TD_BASE = "https://api.twelvedata.com"
TD_WS   = "wss://ws.twelvedata.com/v1/quotes/price"
IST     = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────
def _nse(symbol: str) -> str:
    """Append :NSE exchange suffix."""
    return f"{symbol}:NSE" if ":NSE" not in symbol else symbol


def _strip(symbol: str) -> str:
    return symbol.replace(":NSE", "")


# ─────────────────────────────────────────────────────────────
# REST Client
# ─────────────────────────────────────────────────────────────
class TwelveDataClient:
    """
    REST API client for Twelve Data.
    All methods return plain dicts / lists; no Streamlit deps here.
    """

    BATCH_SIZE = 80   # max symbols per /quote call
    RATE_DELAY = 0.15 # seconds between chunk requests

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "NSE-ORB-Terminal/1.0"})

    # ── Low-level GET ────────────────────────────────────────
    def _get(self, endpoint: str, params: dict, timeout: int = 15) -> dict:
        params["apikey"] = self.api_key
        url = f"{TD_BASE}/{endpoint}"
        try:
            r = self.session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            log.error("TD REST error %s: %s", endpoint, e)
            return {"status": "error", "message": str(e)}

    # ── Validate API key ─────────────────────────────────────
    def test_connection(self) -> tuple[bool, str]:
        """Returns (success, message)."""
        d = self._get("quote", {"symbol": "RELIANCE:NSE"})
        if d.get("status") == "error":
            return False, d.get("message", "Unknown error")
        if "close" in d:
            return True, f"Connected ✓  Exchange: {d.get('exchange','NSE')}  Plan: {d.get('plan','—')}"
        return False, "Unexpected response format"

    # ── Batch quotes ─────────────────────────────────────────
    def get_quotes(self, symbols: list[str]) -> dict:
        """
        Fetch latest quote for multiple symbols.
        Returns {SYM: {open, high, low, close, volume,
                        change, percent_change, ...}}
        """
        results = {}
        chunks = [symbols[i:i+self.BATCH_SIZE]
                  for i in range(0, len(symbols), self.BATCH_SIZE)]

        for chunk in chunks:
            param_syms = ",".join(_nse(s) for s in chunk)
            data = self._get("quote", {"symbol": param_syms})

            if isinstance(data, dict):
                # Single symbol → dict with "close" key
                if "close" in data and len(chunk) == 1:
                    results[chunk[0]] = data
                else:
                    # Multiple symbols → {"SYM:NSE": {...}, ...}
                    for raw_sym, val in data.items():
                        sym = _strip(raw_sym)
                        if isinstance(val, dict) and val.get("status") != "error":
                            results[sym] = val

            if len(chunks) > 1:
                time.sleep(self.RATE_DELAY)

        return results

    # ── 15-minute OHLCV (ORB candle) ────────────────────────
    def get_orb_candle(self, symbol: str) -> Optional[dict]:
        """
        Returns the 9:15 AM IST 15-min candle as:
        {open, high, low, close, volume, datetime}
        Falls back to most recent 15-min candle if 9:15 not found.
        """
        data = self._get("time_series", {
            "symbol":     _nse(symbol),
            "interval":   "15min",
            "outputsize": "4",          # grab last 4 candles to be safe
            "timezone":   "Asia/Kolkata",
        })
        if data.get("status") == "error" or "values" not in data:
            return None

        values = data["values"]
        # Prefer the 09:15 candle
        for v in values:
            if "09:15" in v.get("datetime", ""):
                return {k: float(v[k]) if k != "datetime" else v[k]
                        for k in ("open","high","low","close","volume","datetime")
                        if k in v}
        # Fallback: most recent candle
        if values:
            v = values[0]
            return {k: float(v[k]) if k != "datetime" else v[k]
                    for k in ("open","high","low","close","volume","datetime")
                    if k in v}
        return None

    # ── Batch ORB candles ────────────────────────────────────
    def get_orb_candles_batch(
        self,
        symbols: list[str],
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """
        Returns {SYM: {open, high, low, close, datetime}} for each symbol.
        progress_cb(done, total) called after each fetch.
        """
        results = {}
        total = len(symbols)
        for i, sym in enumerate(symbols):
            candle = self.get_orb_candle(sym)
            if candle:
                results[sym] = candle
            if progress_cb:
                progress_cb(i + 1, total)
            time.sleep(0.12)   # ~8 req/s — stays within free-plan limits
        return results

    # ── RSI (daily) ──────────────────────────────────────────
    def get_rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        data = self._get("rsi", {
            "symbol":      _nse(symbol),
            "interval":    "1day",
            "time_period": period,
            "outputsize":  "1",
        })
        try:
            return float(data["values"][0]["rsi"])
        except (KeyError, IndexError, TypeError):
            return None

    def get_rsi_batch(
        self,
        symbols: list[str],
        period: int = 14,
        max_symbols: int = 40,
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """
        Returns {SYM: rsi_value}.
        max_symbols limits calls on free-tier plans.
        """
        results = {}
        limited = symbols[:max_symbols]
        total   = len(limited)
        for i, sym in enumerate(limited):
            val = self.get_rsi(sym, period)
            if val is not None:
                results[sym] = val
            if progress_cb:
                progress_cb(i + 1, total)
            time.sleep(0.13)
        return results

    # ── Price history for mini chart ─────────────────────────
    def get_intraday(self, symbol: str, interval: str = "5min", bars: int = 78) -> list:
        """Returns list of {datetime, open, high, low, close, volume}."""
        data = self._get("time_series", {
            "symbol":     _nse(symbol),
            "interval":   interval,
            "outputsize": bars,
            "timezone":   "Asia/Kolkata",
        })
        if data.get("status") == "error" or "values" not in data:
            return []
        out = []
        for v in reversed(data["values"]):   # oldest first
            try:
                out.append({
                    "datetime": v["datetime"],
                    "open":     float(v["open"]),
                    "high":     float(v["high"]),
                    "low":      float(v["low"]),
                    "close":    float(v["close"]),
                    "volume":   float(v.get("volume", 0)),
                })
            except (KeyError, ValueError):
                pass
        return out


# ─────────────────────────────────────────────────────────────
# WebSocket Streamer
# ─────────────────────────────────────────────────────────────
class TDWebSocketStreamer:
    """
    Streams real-time price ticks from Twelve Data WebSocket.
    on_price_cb(symbol: str, price: float, ts: str) is called on each tick.
    Runs in a daemon thread; call .start() / .stop().
    """

    CHUNK = 50   # max symbols per subscribe message

    def __init__(self, api_key: str, on_price_cb: Callable, on_status_cb: Optional[Callable] = None):
        self.api_key      = api_key
        self.on_price     = on_price_cb
        self.on_status    = on_status_cb or (lambda s: None)
        self._symbols: list[str] = []
        self._ws          = None
        self._thread       = None
        self._running      = False

    def set_symbols(self, symbols: list[str]):
        self._symbols = symbols

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run(self):
        url = f"{TD_WS}?apikey={self.api_key}"
        self._ws = websocket.WebSocketApp(
            url,
            on_open    = self._on_open,
            on_message = self._on_message,
            on_error   = self._on_error,
            on_close   = self._on_close,
        )
        self.on_status("connecting")
        # reconnect loop
        while self._running:
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.warning("WS run error: %s", e)
            if self._running:
                self.on_status("reconnecting")
                time.sleep(5)

    def _on_open(self, ws):
        self.on_status("connected")
        chunks = [self._symbols[i:i+self.CHUNK]
                  for i in range(0, len(self._symbols), self.CHUNK)]
        for i, chunk in enumerate(chunks):
            msg = json.dumps({
                "action": "subscribe",
                "params": {"symbols": ",".join(_nse(s) for s in chunk)},
            })
            ws.send(msg)
            if i < len(chunks) - 1:
                time.sleep(0.2)

    def _on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
            if msg.get("event") == "price":
                sym   = _strip(msg.get("symbol", ""))
                price = float(msg.get("price", 0))
                ts    = msg.get("timestamp", "")
                if sym and price:
                    self.on_price(sym, price, ts)
        except Exception as e:
            log.debug("WS parse error: %s", e)

    def _on_error(self, ws, error):
        log.error("WS error: %s", error)
        self.on_status(f"error: {error}")

    def _on_close(self, ws, code, msg):
        self.on_status("closed")
