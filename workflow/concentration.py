"""Deterministic sector concentration detection.

Uses yfinance sector data to flag portfolio concentration risk
without any LLM calls — pure code.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import yfinance as yf

logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def _get_sector(ticker: str) -> str:
    """Fetch the sector for a ticker (cached in-process)."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("sector", "Unknown")
    except Exception:
        logger.debug(f"Could not fetch sector for {ticker}, returning 'Unknown'")
        return "Unknown"


def check_sector_concentration(
    ticker: str,
    ticker_sector: str,
    existing_holdings: list[str],
) -> dict:
    """Check if adding *ticker* would increase sector concentration.

    Args:
        ticker: The stock being analysed.
        ticker_sector: Sector of the analysed stock (from yfinance info).
        existing_holdings: List of tickers the user already holds.

    Returns:
        {
            "concentration_risk_flag": bool,
            "correlation_with_holdings": str,   # human-readable description
        }
    """
    if not existing_holdings:
        return {
            "concentration_risk_flag": False,
            "correlation_with_holdings": "No existing holdings provided — no concentration analysis needed.",
        }

    # Map each holding to its sector
    holding_sectors: dict[str, str] = {}
    for h in existing_holdings:
        holding_sectors[h] = _get_sector(h)

    # Count how many holdings share the same sector as the target ticker
    same_sector = [h for h, s in holding_sectors.items() if s == ticker_sector and ticker_sector != "Unknown"]
    same_sector_ratio = len(same_sector) / len(existing_holdings) if existing_holdings else 0

    # Flag if ≥50% of holdings are in the same sector as the new ticker
    concentration_flag = same_sector_ratio >= 0.5

    # Build description
    sector_counts: dict[str, list[str]] = {}
    for h, s in holding_sectors.items():
        sector_counts.setdefault(s, []).append(h)

    parts = []
    if concentration_flag:
        parts.append(
            f"High correlation with existing holdings. {ticker} is in the {ticker_sector} sector. "
            f"The existing portfolio ({', '.join(existing_holdings)}) has "
            f"{len(same_sector)}/{len(existing_holdings)} holdings in the same sector "
            f"({', '.join(same_sector)}). "
            f"Adding {ticker} would further increase {ticker_sector} sector concentration, "
            f"exposing the portfolio to correlated drawdowns during sector-wide selloffs."
        )
    else:
        parts.append(
            f"{ticker} is in the {ticker_sector} sector. "
            f"The existing portfolio has diversified sector exposure — "
            f"adding {ticker} does not create excessive concentration risk."
        )

    return {
        "concentration_risk_flag": concentration_flag,
        "correlation_with_holdings": " ".join(parts),
    }


def check_sector_concentration_from_cache(
    ticker: str,
    ticker_sector: str,
    existing_holdings: list[str],
    sector_map: dict[str, str] | None = None,
) -> dict:
    """Same as check_sector_concentration but accepts a pre-fetched sector map.

    Use this in dry-run mode to avoid yfinance calls.
    """
    if not existing_holdings:
        return {
            "concentration_risk_flag": False,
            "correlation_with_holdings": "No existing holdings provided.",
        }

    if sector_map is None:
        sector_map = {}

    holding_sectors = {h: sector_map.get(h, "Unknown") for h in existing_holdings}
    same_sector = [h for h, s in holding_sectors.items() if s == ticker_sector and ticker_sector != "Unknown"]
    same_sector_ratio = len(same_sector) / len(existing_holdings) if existing_holdings else 0
    concentration_flag = same_sector_ratio >= 0.5

    if concentration_flag:
        desc = (
            f"High correlation with existing holdings. {ticker} is in the {ticker_sector} sector. "
            f"The existing portfolio ({', '.join(existing_holdings)}) has "
            f"{len(same_sector)}/{len(existing_holdings)} holdings in the same sector "
            f"({', '.join(same_sector)}). "
            f"Adding {ticker} would further increase {ticker_sector} sector concentration, "
            f"exposing the portfolio to correlated drawdowns during sector-wide selloffs."
        )
    else:
        desc = (
            f"{ticker} is in the {ticker_sector} sector. "
            f"The existing portfolio has diversified sector exposure — "
            f"adding {ticker} does not create excessive concentration risk."
        )

    return {
        "concentration_risk_flag": concentration_flag,
        "correlation_with_holdings": desc,
    }
