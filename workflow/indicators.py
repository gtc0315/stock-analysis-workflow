"""Pure-Python technical indicator computation from price history.

All functions operate on pandas DataFrames from yfinance's stock.history().
No LLM calls — this is deterministic math.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rsi(hist: pd.DataFrame, period: int = 14) -> float | None:
    """Compute Wilder's RSI (Relative Strength Index).

    Returns a value between 0-100, or None if insufficient data.
    """
    close = hist["Close"]
    if len(close) < period + 1:
        return None

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    # Wilder's smoothing (exponential moving average)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    latest = rsi.iloc[-1]
    if pd.isna(latest):
        return None
    return round(float(latest), 1)


def compute_macd(hist: pd.DataFrame) -> dict:
    """Compute MACD (12/26/9 standard).

    Returns: {macd_line, signal_line, histogram, direction}
    """
    close = hist["Close"]
    if len(close) < 26:
        return {"macd_line": 0, "signal_line": 0, "histogram": 0, "direction": "neutral"}

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    latest_macd = float(macd_line.iloc[-1])
    latest_signal = float(signal_line.iloc[-1])
    latest_hist = float(histogram.iloc[-1])

    # Direction based on MACD vs signal and histogram trend
    if latest_macd > latest_signal and latest_hist > 0:
        direction = "bullish"
    elif latest_macd < latest_signal and latest_hist < 0:
        direction = "bearish"
    else:
        direction = "neutral"

    return {
        "macd_line": round(latest_macd, 2),
        "signal_line": round(latest_signal, 2),
        "histogram": round(latest_hist, 2),
        "direction": direction,
    }


def compute_sma(hist: pd.DataFrame, current_price: float) -> dict:
    """Compute Simple Moving Averages and price relationship.

    Returns: {sma_50, sma_200, price_vs_50, price_vs_200, golden_cross}
    """
    close = hist["Close"]

    sma_50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    sma_200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    price_vs_50 = "above" if sma_50 and current_price > sma_50 else "below" if sma_50 else "unknown"
    price_vs_200 = "above" if sma_200 and current_price > sma_200 else "below" if sma_200 else "unknown"

    golden_cross = bool(sma_50 and sma_200 and sma_50 > sma_200)

    return {
        "sma_50": round(sma_50, 2) if sma_50 else None,
        "sma_200": round(sma_200, 2) if sma_200 else None,
        "price_vs_50": price_vs_50,
        "price_vs_200": price_vs_200,
        "golden_cross": golden_cross,
    }


def compute_volume_stats(hist: pd.DataFrame) -> dict:
    """Compute volume statistics.

    Returns: {avg_5d, avg_30d, ratio, assessment}
    """
    vol = hist["Volume"]
    if len(vol) < 5:
        return {"avg_5d": 0, "avg_30d": 0, "ratio": 1.0, "assessment": "insufficient data"}

    avg_5d = float(vol.tail(5).mean())
    avg_30d = float(vol.tail(30).mean()) if len(vol) >= 30 else avg_5d

    ratio = round(avg_5d / avg_30d, 2) if avg_30d > 0 else 1.0

    if ratio > 1.3:
        assessment = "above average volume — strong conviction in recent moves"
    elif ratio < 0.7:
        assessment = "below average volume — weak conviction in recent moves"
    else:
        assessment = "normal volume — no unusual activity"

    return {
        "avg_5d": int(avg_5d),
        "avg_30d": int(avg_30d),
        "ratio": ratio,
        "assessment": assessment,
    }


def compute_pivot_supports_resistances(hist: pd.DataFrame, current_price: float) -> dict:
    """Compute support and resistance levels from pivot points and price history.

    Uses classic pivot point formula + recent highs/lows.
    Returns: {supports: [float], resistances: [float]}
    """
    if len(hist) < 5:
        return {"supports": [round(current_price * 0.95, 2)], "resistances": [round(current_price * 1.05, 2)]}

    # Recent high/low/close for pivot calculation
    recent = hist.tail(20)
    high = float(recent["High"].max())
    low = float(recent["Low"].min())
    close = float(recent["Close"].iloc[-1])

    # Classic pivot points
    pivot = (high + low + close) / 3
    s1 = 2 * pivot - high
    s2 = pivot - (high - low)
    r1 = 2 * pivot - low
    r2 = pivot + (high - low)

    # Also use rolling 20-day and 50-day lows/highs
    supports_raw = [s1, s2]
    resistances_raw = [r1, r2]

    if len(hist) >= 50:
        supports_raw.append(float(hist["Low"].tail(50).min()))
        resistances_raw.append(float(hist["High"].tail(50).max()))

    # Round number levels near current price (scaled by price level)
    if current_price >= 50:
        base = round(current_price, -1)  # nearest $10
        offsets = [-20, -10, 10, 20]
    elif current_price >= 10:
        base = round(current_price, -1)  # nearest $10
        offsets = [-10, -5, 5, 10]
    else:
        base = round(current_price)  # nearest $1
        offsets = [-2, -1, 1, 2]

    for offset in offsets:
        level = base + offset
        if level > 0 and level < current_price:
            supports_raw.append(float(level))
        elif level > current_price:
            resistances_raw.append(float(level))

    # Filter: supports below current price, resistances above
    supports = sorted(set(round(s, 2) for s in supports_raw if s < current_price), reverse=True)[:3]
    resistances = sorted(set(round(r, 2) for r in resistances_raw if r > current_price))[:3]

    # Ensure at least one level each
    if not supports:
        supports = [round(current_price * 0.95, 2)]
    if not resistances:
        resistances = [round(current_price * 1.05, 2)]

    return {"supports": supports, "resistances": resistances}


def compute_bollinger_bands(hist: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> dict:
    """Compute Bollinger Bands (20-period SMA +/- 2 std dev).

    Returns: {upper, middle, lower, bandwidth, pct_b}
    - bandwidth: (upper - lower) / middle — measures volatility
    - pct_b: (price - lower) / (upper - lower) — where price sits in the band (0=lower, 1=upper)
    """
    close = hist["Close"]
    if len(close) < period:
        return {"upper": None, "middle": None, "lower": None, "bandwidth": None, "pct_b": None}

    middle = float(close.tail(period).mean())
    std = float(close.tail(period).std())
    upper = round(middle + num_std * std, 2)
    lower = round(middle - num_std * std, 2)
    middle = round(middle, 2)

    bandwidth = round((upper - lower) / middle, 4) if middle > 0 else None
    price = float(close.iloc[-1])
    pct_b = round((price - lower) / (upper - lower), 2) if upper != lower else 0.5

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
        "pct_b": pct_b,
    }


def classify_rsi_signal(rsi: float | None) -> str:
    """Classify RSI into signal category."""
    if rsi is None:
        return "neutral"
    if rsi < 30:
        return "oversold"
    if rsi > 70:
        return "overbought"
    return "neutral"


def classify_trend(current_price: float, sma_50: float | None, sma_200: float | None) -> str:
    """Classify price trend from moving average relationships."""
    if sma_50 is None or sma_200 is None:
        return "consolidation"

    if current_price > sma_50 > sma_200:
        return "uptrend"
    elif current_price < sma_50 < sma_200:
        return "downtrend"
    else:
        return "consolidation"


def build_technical_indicators(hist: pd.DataFrame, current_price: float) -> dict:
    """Master function: compute all technical indicators from price history.

    Returns a flat dict with all computed values for use by Phase 0 and Worker 3a.
    """
    rsi = compute_rsi(hist)
    macd = compute_macd(hist)
    sma = compute_sma(hist, current_price)
    volume = compute_volume_stats(hist)
    pivots = compute_pivot_supports_resistances(hist, current_price)
    bollinger = compute_bollinger_bands(hist)
    trend = classify_trend(current_price, sma["sma_50"], sma["sma_200"])
    rsi_signal = classify_rsi_signal(rsi)

    return {
        # RSI
        "rsi": rsi,
        "rsi_signal": rsi_signal,
        # MACD
        "macd_line": macd["macd_line"],
        "macd_signal": macd["signal_line"],
        "macd_histogram": macd["histogram"],
        "macd_direction": macd["direction"],
        # Moving averages
        "sma_50": sma["sma_50"],
        "sma_200": sma["sma_200"],
        "price_vs_50_sma": sma["price_vs_50"],
        "price_vs_200_sma": sma["price_vs_200"],
        "golden_cross": sma["golden_cross"],
        # Bollinger Bands
        "bollinger_upper": bollinger["upper"],
        "bollinger_middle": bollinger["middle"],
        "bollinger_lower": bollinger["lower"],
        "bollinger_bandwidth": bollinger["bandwidth"],
        "bollinger_pct_b": bollinger["pct_b"],
        # Trend
        "trend": trend,
        # Volume
        "volume_avg_5d": volume["avg_5d"],
        "volume_avg_30d": volume["avg_30d"],
        "volume_ratio": volume["ratio"],
        "volume_assessment": volume["assessment"],
        # Support / Resistance
        "support_candidates": pivots["supports"],
        "resistance_candidates": pivots["resistances"],
    }
