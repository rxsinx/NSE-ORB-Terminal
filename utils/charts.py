"""
charts.py
─────────
Plotly chart builders for the NSE ORB Terminal.
All functions return plotly Figure objects ready for st.plotly_chart().
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Optional

# ── Colour palette ───────────────────────────────────────────
BG      = "#040d14"
BG2     = "#071520"
GRID    = "#1a3a52"
ACCENT  = "#00e5ff"
BULL    = "#00e676"
BEAR    = "#ff1744"
WARN    = "#ffcc02"
TEXT    = "#c8dbe8"
TEXT2   = "#7fa8c2"

_layout_base = dict(
    paper_bgcolor = BG,
    plot_bgcolor  = BG2,
    font          = dict(color=TEXT, family="Share Tech Mono, monospace", size=11),
    margin        = dict(l=10, r=10, t=30, b=10),
    xaxis         = dict(gridcolor=GRID, zerolinecolor=GRID, showgrid=True),
    yaxis         = dict(gridcolor=GRID, zerolinecolor=GRID, showgrid=True),
)


# ─────────────────────────────────────────────────────────────
# Mini intraday candlestick with ORB overlay
# ─────────────────────────────────────────────────────────────
def orb_candlestick(
    candles: list[dict],
    orb_high: float,
    orb_low:  float,
    symbol:   str,
    height:   int = 350,
) -> go.Figure:
    """
    candles: list of {datetime, open, high, low, close, volume}
    Draws candlestick + ORB high/low bands + volume bars.
    """
    if not candles:
        return _empty_fig("No intraday data")

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"])

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.03,
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x     = df["datetime"],
        open  = df["open"],
        high  = df["high"],
        low   = df["low"],
        close = df["close"],
        name  = symbol,
        increasing_line_color  = BULL,
        decreasing_line_color  = BEAR,
        increasing_fillcolor   = BULL,
        decreasing_fillcolor   = BEAR,
    ), row=1, col=1)

    # ORB high line
    if orb_high > 0:
        fig.add_hline(
            y=orb_high, line_color=BULL, line_dash="dash",
            line_width=1.5, opacity=0.8,
            annotation_text=f" ORB H {orb_high:.2f}",
            annotation_font_color=BULL,
            row=1, col=1,
        )
    # ORB low line
    if orb_low > 0:
        fig.add_hline(
            y=orb_low, line_color=BEAR, line_dash="dash",
            line_width=1.5, opacity=0.8,
            annotation_text=f" ORB L {orb_low:.2f}",
            annotation_font_color=BEAR,
            row=1, col=1,
        )
    # Shaded ORB zone
    if orb_high > 0 and orb_low > 0:
        fig.add_hrect(
            y0=orb_low, y1=orb_high,
            fillcolor="rgba(0,229,255,0.05)",
            line_width=0,
            row=1, col=1,
        )

    # Volume bars
    colors = [BULL if c >= o else BEAR for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(
        x=df["datetime"], y=df["volume"],
        marker_color=colors, name="Volume", opacity=0.6,
    ), row=2, col=1)

    layout = dict(**_layout_base)
    layout.update(
        height         = height,
        title          = dict(text=f"{symbol} — Intraday", font_color=ACCENT, font_size=13),
        showlegend     = False,
        xaxis_rangeslider_visible = False,
        xaxis2         = dict(gridcolor=GRID, zerolinecolor=GRID),
        yaxis2         = dict(gridcolor=GRID, zerolinecolor=GRID, title="Vol"),
    )
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────
# Status distribution donut
# ─────────────────────────────────────────────────────────────
def status_donut(stats: dict) -> go.Figure:
    labels  = ["Breakout ↑", "Breakdown ↓", "Watching", "ORB Set"]
    values  = [
        stats.get("breakouts", 0),
        stats.get("breakdowns", 0),
        stats.get("watching", 0),
        stats.get("orb_set", 0),
    ]
    colors  = [BULL, BEAR, WARN, TEXT2]

    fig = go.Figure(go.Pie(
        labels    = labels,
        values    = values,
        hole      = 0.62,
        marker    = dict(colors=colors, line=dict(color=BG, width=2)),
        textinfo  = "label+value",
        textfont  = dict(size=11, color=TEXT),
        hoverinfo = "label+percent+value",
    ))
    fig.update_layout(
        **_layout_base,
        height    = 260,
        showlegend= False,
        margin    = dict(l=10, r=10, t=10, b=10),
        annotations=[dict(
            text=f"<b>{stats.get('total',0)}</b><br><span style='font-size:10px'>STOCKS</span>",
            x=0.5, y=0.5, showarrow=False,
            font=dict(color=ACCENT, size=16),
        )],
    )
    return fig


# ─────────────────────────────────────────────────────────────
# RSI histogram
# ─────────────────────────────────────────────────────────────
def rsi_histogram(df: pd.DataFrame) -> go.Figure:
    rsi = df["rsi"].dropna()
    fig = go.Figure(go.Histogram(
        x       = rsi,
        nbinsx  = 20,
        marker_color = ACCENT,
        opacity = 0.75,
    ))
    # Oversold / overbought bands
    fig.add_vrect(x0=0, x1=30, fillcolor=f"rgba(255,23,68,0.08)", line_width=0)
    fig.add_vrect(x0=70, x1=100, fillcolor=f"rgba(0,230,118,0.08)", line_width=0)
    fig.add_vline(x=30, line_color=BEAR, line_dash="dot", line_width=1)
    fig.add_vline(x=70, line_color=BULL, line_dash="dot", line_width=1)

    layout = dict(**_layout_base)
    layout.update(
        height = 200,
        title  = dict(text="RSI Distribution", font_color=ACCENT, font_size=12),
        xaxis  = dict(title="RSI", gridcolor=GRID),
        yaxis  = dict(title="Count", gridcolor=GRID),
        margin = dict(l=10, r=10, t=35, b=10),
    )
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────
# Sector breakdown bar chart
# ─────────────────────────────────────────────────────────────
def sector_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_fig("No data")

    grp = df.groupby("sector").agg(
        total      = ("symbol", "count"),
        breakouts  = ("status", lambda x: (x == "BREAKOUT").sum()),
        breakdowns = ("status", lambda x: (x == "BREAKDOWN").sum()),
    ).sort_values("total", ascending=True).tail(15)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=grp.index, x=grp["total"],
        name="Total", orientation="h",
        marker_color=TEXT2, opacity=0.4,
    ))
    fig.add_trace(go.Bar(
        y=grp.index, x=grp["breakouts"],
        name="Breakout", orientation="h",
        marker_color=BULL,
    ))
    fig.add_trace(go.Bar(
        y=grp.index, x=grp["breakdowns"],
        name="Breakdown", orientation="h",
        marker_color=BEAR,
    ))

    layout = dict(**_layout_base)
    layout.update(
        height     = 380,
        barmode    = "overlay",
        title      = dict(text="By Sector", font_color=ACCENT, font_size=12),
        xaxis      = dict(title="Stocks", gridcolor=GRID),
        yaxis      = dict(gridcolor=GRID),
        legend     = dict(font_color=TEXT, bgcolor=BG2),
        margin     = dict(l=10, r=10, t=35, b=10),
    )
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────
# ORB range scatter (range% vs change%)
# ─────────────────────────────────────────────────────────────
def orb_scatter(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty_fig("No data")

    color_map = {
        "BREAKOUT":     BULL,
        "BREAKDOWN":    BEAR,
        "WATCHING_HIGH":WARN,
        "WATCHING_LOW": WARN,
        "ORB_SET":      TEXT2,
    }
    df2 = df[df["orb_captured"]].copy()
    if df2.empty:
        return _empty_fig("Awaiting ORB capture")

    colors = df2["status"].map(color_map).fillna(TEXT2)

    fig = go.Figure(go.Scatter(
        x    = df2["orb_range_pct"],
        y    = df2["change_pct"],
        mode = "markers+text",
        text = df2["symbol"],
        textposition = "top center",
        textfont     = dict(size=8, color=TEXT2),
        marker       = dict(
            color  = colors,
            size   = 8,
            opacity= 0.8,
            line   = dict(color=BG, width=0.5),
        ),
        hovertemplate = (
            "<b>%{text}</b><br>"
            "ORB Range: %{x:.2f}%<br>"
            "Change: %{y:.2f}%<br>"
            "<extra></extra>"
        ),
    ))
    fig.add_hline(y=0, line_color=GRID, line_width=1)

    layout = dict(**_layout_base)
    layout.update(
        height = 320,
        title  = dict(text="ORB Range % vs Price Change %", font_color=ACCENT, font_size=12),
        xaxis  = dict(title="ORB Range %", gridcolor=GRID),
        yaxis  = dict(title="Change %", gridcolor=GRID),
        margin = dict(l=10, r=10, t=35, b=10),
    )
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────
# Alert timeline
# ─────────────────────────────────────────────────────────────
def alert_timeline(alerts: list[dict]) -> go.Figure:
    if not alerts:
        return _empty_fig("No alerts yet")

    df = pd.DataFrame(alerts)
    bulls = df[df["type"] == "BREAKOUT"]
    bears = df[df["type"] == "BREAKDOWN"]

    fig = go.Figure()
    if not bulls.empty:
        fig.add_trace(go.Scatter(
            x=bulls["time"], y=bulls["cmp"],
            mode="markers+text",
            text=bulls["symbol"],
            textposition="top center",
            textfont=dict(size=9, color=BULL),
            marker=dict(color=BULL, size=10, symbol="triangle-up"),
            name="Breakout",
        ))
    if not bears.empty:
        fig.add_trace(go.Scatter(
            x=bears["time"], y=bears["cmp"],
            mode="markers+text",
            text=bears["symbol"],
            textposition="bottom center",
            textfont=dict(size=9, color=BEAR),
            marker=dict(color=BEAR, size=10, symbol="triangle-down"),
            name="Breakdown",
        ))

    layout = dict(**_layout_base)
    layout.update(
        height = 280,
        title  = dict(text="Alert Timeline", font_color=ACCENT, font_size=12),
        xaxis  = dict(title="Time (IST)", gridcolor=GRID),
        yaxis  = dict(title="Price ₹", gridcolor=GRID),
        legend = dict(font_color=TEXT, bgcolor=BG2),
        margin = dict(l=10, r=10, t=35, b=10),
    )
    fig.update_layout(**layout)
    return fig


# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────
def _empty_fig(msg: str = "No data") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, x=0.5, y=0.5, showarrow=False,
                        font=dict(color=TEXT2, size=13))
    fig.update_layout(**_layout_base, height=200,
                      margin=dict(l=10, r=10, t=10, b=10))
    return fig
