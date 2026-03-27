"""
orb_engine.py
─────────────
Core ORB (Opening Range Breakout) engine.

Responsibilities:
  • Maintain a DataFrame of all scanned stocks
  • Capture ORB high/low from the 9:15 AM 15-min candle
  • Evaluate breakout / breakdown status on every price update
  • Maintain an alert log (timestamped events)
  • Market phase detection (IST)

Thread-safe: uses a threading.Lock for shared state.
"""

import threading
import logging
from datetime import datetime, date
from typing import Optional
import pandas as pd
import numpy as np
import pytz

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


# ─────────────────────────────────────────────────────────────
# Market phase helpers
# ─────────────────────────────────────────────────────────────
def ist_now() -> datetime:
    return datetime.now(IST)


def market_phase(dt: Optional[datetime] = None) -> str:
    """
    Returns one of:
      'pre_market'   — before 09:00
      'pre_open'     — 09:00–09:14
      'orb_window'   — 09:15–09:29  (ORB capture window)
      'market_open'  — 09:30–15:29  (monitoring)
      'closing'      — 15:30
      'closed'       — after 15:30 or weekends
    """
    dt = dt or ist_now()
    if dt.weekday() >= 5:          # Saturday / Sunday
        return "closed"
    h, m = dt.hour, dt.minute
    mins = h * 60 + m
    if mins < 9 * 60:              return "pre_market"
    if mins < 9 * 60 + 15:        return "pre_open"
    if mins < 9 * 60 + 30:        return "orb_window"
    if mins < 15 * 60 + 30:       return "market_open"
    return "closed"


def is_market_open(dt: Optional[datetime] = None) -> bool:
    return market_phase(dt) in ("orb_window", "market_open")


# ─────────────────────────────────────────────────────────────
# ORBEngine
# ─────────────────────────────────────────────────────────────
COLUMNS = [
    "symbol", "sector", "cmp", "open", "prev_close",
    "orb_high", "orb_low", "orb_range_pct",
    "change_pct", "rsi",
    "status",           # ORB_SET | WATCHING_HIGH | WATCHING_LOW | BREAKOUT | BREAKDOWN
    "alert_fired",      # bool
    "alert_time",       # HH:MM string or ""
    "dist_to_high_pct", # (orb_high - cmp) / cmp * 100
    "dist_to_low_pct",  # (cmp - orb_low) / cmp * 100
    "orb_captured",     # bool — True once 9:15 candle is locked
]

WATCHING_THRESHOLD = 0.30   # % within ORB boundary to flag as WATCHING


class ORBEngine:
    def __init__(self):
        self._lock   = threading.Lock()
        self._df     = pd.DataFrame(columns=COLUMNS)
        self._alerts: list[dict] = []
        self.scan_ts: Optional[datetime] = None
        self.orb_ts:  Optional[datetime] = None

    # ── Initialise stock list ────────────────────────────────
    def init_stocks(self, universe: list[tuple]):
        """
        universe: [(symbol, base_price, sector), ...]
        Populates DataFrame with defaults; real prices filled later.
        """
        rows = []
        for sym, base_px, sector in universe:
            rows.append({
                "symbol":          sym,
                "sector":          sector,
                "cmp":             float(base_px),
                "open":            float(base_px),
                "prev_close":      float(base_px),
                "orb_high":        0.0,
                "orb_low":         0.0,
                "orb_range_pct":   0.0,
                "change_pct":      0.0,
                "rsi":             50.0,
                "status":          "ORB_SET",
                "alert_fired":     False,
                "alert_time":      "",
                "dist_to_high_pct": 0.0,
                "dist_to_low_pct":  0.0,
                "orb_captured":    False,
            })
        with self._lock:
            self._df = pd.DataFrame(rows)

    # ── Update live quotes ───────────────────────────────────
    def update_quotes(self, quotes: dict):
        """
        quotes: {SYM: {open, close, percent_change, ...}}
        Updates cmp, open, change_pct; then re-evaluates status.
        """
        with self._lock:
            for sym, q in quotes.items():
                mask = self._df["symbol"] == sym
                if not mask.any():
                    continue
                try:
                    cmp  = float(q.get("close", q.get("price", 0)) or 0)
                    opn  = float(q.get("open", 0) or 0)
                    chg  = float(q.get("percent_change", 0) or 0)
                    if cmp <= 0:
                        continue
                    self._df.loc[mask, "cmp"]        = round(cmp, 2)
                    if opn > 0:
                        self._df.loc[mask, "open"]   = round(opn, 2)
                    self._df.loc[mask, "change_pct"] = round(chg, 2)
                except (ValueError, TypeError):
                    pass
            self._recompute_status()

    # ── Update single price (WebSocket tick) ─────────────────
    def update_price(self, symbol: str, price: float):
        with self._lock:
            mask = self._df["symbol"] == symbol
            if not mask.any():
                return
            self._df.loc[mask, "cmp"] = round(price, 2)
            opn = float(self._df.loc[mask, "open"].iloc[0])
            if opn > 0:
                chg = (price - opn) / opn * 100
                self._df.loc[mask, "change_pct"] = round(chg, 2)
            self._recompute_status_single(symbol)

    # ── Apply ORB candles ────────────────────────────────────
    def apply_orb_candles(self, candles: dict):
        """
        candles: {SYM: {open, high, low, close, datetime}}
        Locks the ORB range for each symbol.
        """
        with self._lock:
            for sym, c in candles.items():
                mask = self._df["symbol"] == sym
                if not mask.any():
                    continue
                try:
                    orb_h = float(c["high"])
                    orb_l = float(c["low"])
                    opn   = float(c["open"])
                    rng   = (orb_h - orb_l) / opn * 100 if opn else 0
                    self._df.loc[mask, "orb_high"]      = round(orb_h, 2)
                    self._df.loc[mask, "orb_low"]       = round(orb_l, 2)
                    self._df.loc[mask, "orb_range_pct"] = round(rng, 2)
                    self._df.loc[mask, "open"]          = round(opn, 2)
                    self._df.loc[mask, "orb_captured"]  = True
                except (KeyError, ValueError, TypeError):
                    pass
            self.orb_ts = ist_now()
            self._recompute_status()

    # ── Apply RSI values ─────────────────────────────────────
    def apply_rsi(self, rsi_map: dict):
        with self._lock:
            for sym, rsi_val in rsi_map.items():
                mask = self._df["symbol"] == sym
                if mask.any():
                    self._df.loc[mask, "rsi"] = round(float(rsi_val), 1)

    # ── Status recomputation ─────────────────────────────────
    def _recompute_status(self):
        """Recalculate status for all rows (call inside lock)."""
        for sym in self._df["symbol"].tolist():
            self._recompute_status_single(sym, inside_lock=True)

    def _recompute_status_single(self, symbol: str, inside_lock: bool = False):
        """Recompute status for one symbol. Fires alerts if needed."""
        mask = self._df["symbol"] == symbol
        row  = self._df.loc[mask].iloc[0]

        cmp     = float(row["cmp"])
        orb_h   = float(row["orb_high"])
        orb_l   = float(row["orb_low"])
        fired   = bool(row["alert_fired"])
        captured = bool(row["orb_captured"])

        if not captured or orb_h == 0 or orb_l == 0:
            return

        # Distance metrics
        dist_h = (orb_h - cmp) / cmp * 100
        dist_l = (cmp - orb_l) / cmp * 100
        self._df.loc[mask, "dist_to_high_pct"] = round(dist_h, 2)
        self._df.loc[mask, "dist_to_low_pct"]  = round(dist_l, 2)

        phase = market_phase()

        if cmp > orb_h:
            new_status = "BREAKOUT"
        elif cmp < orb_l:
            new_status = "BREAKDOWN"
        elif dist_h <= WATCHING_THRESHOLD:
            new_status = "WATCHING_HIGH"
        elif dist_l <= WATCHING_THRESHOLD:
            new_status = "WATCHING_LOW"
        else:
            new_status = "ORB_SET"

        self._df.loc[mask, "status"] = new_status

        # Fire alert only once, and only during market hours
        if not fired and new_status in ("BREAKOUT", "BREAKDOWN") and phase == "market_open":
            now_str = ist_now().strftime("%H:%M:%S")
            self._df.loc[mask, "alert_fired"] = True
            self._df.loc[mask, "alert_time"]  = now_str
            self._alerts.append({
                "time":    now_str,
                "symbol":  symbol,
                "sector":  str(row["sector"]),
                "type":    new_status,
                "cmp":     cmp,
                "orb_ref": orb_h if new_status == "BREAKOUT" else orb_l,
                "change_pct": float(row["change_pct"]),
                "rsi":     float(row["rsi"]),
            })
            log.info("ALERT %s %s @ %.2f", new_status, symbol, cmp)

    # ── Public read methods (return copies) ──────────────────
    def get_df(self) -> pd.DataFrame:
        with self._lock:
            return self._df.copy()

    def get_alerts(self) -> list[dict]:
        with self._lock:
            return list(self._alerts)

    def get_stock(self, symbol: str) -> Optional[dict]:
        with self._lock:
            mask = self._df["symbol"] == symbol
            if not mask.any():
                return None
            return self._df.loc[mask].iloc[0].to_dict()

    def get_stats(self) -> dict:
        with self._lock:
            df = self._df
            return {
                "total":     len(df),
                "orb_set":   int((df["status"] == "ORB_SET").sum()),
                "breakouts": int((df["status"] == "BREAKOUT").sum()),
                "breakdowns":int((df["status"] == "BREAKDOWN").sum()),
                "watching":  int(df["status"].str.startswith("WATCHING").sum()),
                "alerts":    len(self._alerts),
                "orb_captured": int(df["orb_captured"].sum()),
            }

    def clear_alerts(self):
        with self._lock:
            self._alerts.clear()
            self._df["alert_fired"] = False
            self._df["alert_time"]  = ""

    def reset(self):
        with self._lock:
            self._df     = pd.DataFrame(columns=COLUMNS)
            self._alerts = []
            self.scan_ts = None
            self.orb_ts  = None
