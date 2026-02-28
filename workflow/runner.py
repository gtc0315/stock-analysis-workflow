#!/usr/bin/env python3
"""Main orchestrator — runs the full stock analysis pipeline.

Swarm Architecture: many small, focused LLM calls + deterministic code phases.

Phase 0  (CODE):  Parse yfinance, compute technical indicators, check concentration
Phase 1-3 (LLM):  9 parallel workers — news, analyst, 4x fundamental, tech interp, catalysts, risks
Phase 4  (LLM):  2 sequential workers — recommendation, narratives
Phase 5  (CODE):  Assemble final output with deterministic math
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml
import yfinance as yf
from pydantic import ValidationError

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from adapters import AnthropicAdapter, OllamaAdapter, OpenAIAdapter
from workflow.schema import (
    AnalysisResult,
    AnalystWorkerOutput,
    CatalystRiskOutput,
    CatalystWorkerOutput,
    DataGatheringOutput,
    DecisionOutput,
    DimensionWorkerOutput,
    FundamentalAnalysisOutput,
    NarrativeOutput,
    NewsWorkerOutput,
    RecommendationOutput,
    RiskProfile,
    RiskWorkerOutput,
    TechInterpretationOutput,
    TechnicalAnalysisOutput,
    get_schema_dict,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
RESULTS_DIR = PROJECT_ROOT / "results"
MOCK_DIR = PROJECT_ROOT / "tests" / "fixtures"


# ── Config & Adapter ──────────────────────────────────────────────────────────


def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def create_adapter(provider: str, config: dict):
    """Create an LLM adapter from config."""
    providers = config["providers"]

    if provider == "anthropic":
        cfg = providers["anthropic"]
        return AnthropicAdapter(
            model=cfg.get("default_model", "claude-sonnet-4-5-20250929"),
            api_key_env=cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
        )
    elif provider == "openai":
        cfg = providers["openai"]
        return OpenAIAdapter(
            model=cfg.get("default_model", "gpt-4o"),
            api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
        )
    elif provider == "ollama":
        cfg = providers["ollama"]
        return OllamaAdapter(
            model=cfg.get("default_model", "llama3"),
            base_url=cfg.get("base_url", "http://localhost:11434"),
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _clone_adapter(adapter):
    """Create a lightweight copy for thread-safe parallel execution.

    Each clone gets its own `last_usage` dict to prevent race conditions
    when multiple workers write to it concurrently. The underlying API client
    is shared (it's thread-safe), only the mutable state is isolated.
    """
    if isinstance(adapter, OllamaAdapter):
        return OllamaAdapter(model=adapter.model, base_url=adapter.base_url, timeout=adapter.timeout)
    if isinstance(adapter, AnthropicAdapter):
        clone = object.__new__(AnthropicAdapter)
        clone.client = adapter.client  # httpx client is thread-safe
        clone.model = adapter.model
        clone.last_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
        return clone
    if isinstance(adapter, OpenAIAdapter):
        clone = object.__new__(OpenAIAdapter)
        clone.client = adapter.client  # openai client is thread-safe
        clone.model = adapter.model
        clone.last_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
        return clone
    return adapter


def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_money(value) -> str:
    """Format a dollar amount for prompt display."""
    if value is None:
        return "N/A"
    num = float(value)
    sign = "-" if num < 0 else ""
    abs_val = abs(num)
    if abs_val >= 1e9:
        return f"{sign}${abs_val/1e9:.1f}B"
    elif abs_val >= 1e6:
        return f"{sign}${abs_val/1e6:.0f}M"
    elif abs_val >= 1e3:
        return f"{sign}${abs_val/1e3:.0f}K"
    return f"{sign}${abs_val:.0f}"


def _format_pct(value) -> str:
    """Format a decimal ratio as a percentage string for prompt display."""
    if value is None:
        return "N/A"
    return f"{float(value)*100:.1f}%"


def _fill_prompt(template: str, **kwargs) -> str:
    """Replace {{key}} placeholders in a prompt template."""
    for key, value in kwargs.items():
        template = template.replace(f"{{{{{key}}}}}", str(value) if value is not None else "N/A")
    return template


# ── Market Data ───────────────────────────────────────────────────────────────


def fetch_market_data(ticker: str) -> tuple:
    """Fetch market data using yfinance.

    Returns:
        (market_data_dict, price_history_dataframe)
    """
    logger.info(f"Fetching market data for {ticker}...")
    stock = yf.Ticker(ticker)
    info = stock.info

    hist = stock.history(period="1y")
    recent_hist = stock.history(period="5d")

    market_data = {
        "ticker": ticker,
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
        "previous_close": info.get("previousClose", 0),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "ps_ratio": info.get("priceToSalesTrailing12Months"),
        "market_cap": info.get("marketCap", 0),
        "market_cap_billions": round(info.get("marketCap", 0) / 1e9, 2),
        "week_52_high": info.get("fiftyTwoWeekHigh", 0),
        "week_52_low": info.get("fiftyTwoWeekLow", 0),
        "beta": info.get("beta"),
        "short_interest_pct": info.get("shortPercentOfFloat"),
        "average_volume": info.get("averageVolume", 0),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margins": info.get("profitMargins"),
        "free_cash_flow": info.get("freeCashflow"),
        "total_debt": info.get("totalDebt"),
        "total_cash": info.get("totalCash"),
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "company_name": info.get("longName", ticker),
        "dividend_yield": info.get("dividendYield"),
        "fifty_day_average": info.get("fiftyDayAverage"),
        "two_hundred_day_average": info.get("twoHundredDayAverage"),
        "next_earnings_date": None,
        "recent_prices": (
            json.loads(recent_hist[["Close", "Volume"]].tail(5).to_json())
            if not recent_hist.empty
            else {}
        ),
        "data_timestamp": datetime.now().isoformat(),
    }

    # Try to get next earnings date
    try:
        cal = stock.calendar
        if cal is not None and hasattr(cal, 'get'):
            ed = cal.get("Earnings Date")
            if ed:
                market_data["next_earnings_date"] = str(ed[0]) if isinstance(ed, list) else str(ed)
    except Exception:
        pass

    return market_data, hist


# ── LLM Call Logging ──────────────────────────────────────────────────────────


def log_llm_call(step: str, model: str, usage: dict, prompt_hash: str):
    """Log LLM call details."""
    cost = estimate_cost(model, usage)
    logger.info(
        f"  [{step}] model={model} | tokens_in={usage['input_tokens']} "
        f"tokens_out={usage['output_tokens']} | latency={usage['latency_ms']}ms | cost=${cost:.4f}"
    )


def estimate_cost(model: str, usage: dict) -> float:
    """Rough cost estimation per model."""
    rates = {
        "claude-sonnet-4-5-20250929": (3.0 / 1e6, 15.0 / 1e6),
        "gpt-4o": (2.5 / 1e6, 10.0 / 1e6),
        "llama3": (0, 0),
    }
    input_rate, output_rate = rates.get(model, (0.01 / 1e6, 0.03 / 1e6))
    return usage["input_tokens"] * input_rate + usage["output_tokens"] * output_rate


# ── Output Normalization ──────────────────────────────────────────────────────


def _normalize_output(data: dict, schema_class) -> dict:
    """Normalize LLM output before Pydantic validation.

    Handles common small-model issues:
    - Field name aliases (sell_ratings -> sell_count)
    - Null values in required numeric fields -> defaults
    - String "null"/"None" -> None
    - Numeric strings -> numbers
    """
    if not isinstance(data, dict):
        return data

    # Clean string nulls everywhere
    for key, val in list(data.items()):
        if isinstance(val, str) and val.strip().lower() in ("null", "none", "n/a", ""):
            data[key] = None

    # Schema-specific normalizations
    normalizers = {
        DataGatheringOutput: _normalize_data_gathering,
        FundamentalAnalysisOutput: _normalize_fundamental,
        TechnicalAnalysisOutput: _normalize_technical,
        CatalystRiskOutput: _normalize_catalyst,
        RecommendationOutput: _normalize_recommendation,
        # Worker schemas
        NewsWorkerOutput: _normalize_news_worker,
        AnalystWorkerOutput: _normalize_analyst_worker,
        DimensionWorkerOutput: _normalize_dimension_worker,
        TechInterpretationOutput: _normalize_tech_interpretation,
        CatalystWorkerOutput: _normalize_catalyst_worker,
        RiskWorkerOutput: _normalize_risk_worker,
    }

    normalizer = normalizers.get(schema_class)
    if normalizer:
        data = normalizer(data)

    return data


# --- Normalizers for legacy full-step schemas ---


def _normalize_data_gathering(data: dict) -> dict:
    """Fix common Step 1 issues."""
    ac = data.get("analyst_consensus")
    if isinstance(ac, dict):
        alias_map = {
            "buy_ratings": "buy_count", "buys": "buy_count", "buy": "buy_count",
            "hold_ratings": "hold_count", "holds": "hold_count", "hold": "hold_count",
            "sell_ratings": "sell_count", "sells": "sell_count", "sell": "sell_count",
            "target_price": "average_target_price", "avg_target": "average_target_price",
            "avg_target_price": "average_target_price", "consensus_target": "average_target_price",
            "mean_target_price": "average_target_price",
        }
        normalized_ac = {}
        for k, v in ac.items():
            canonical = alias_map.get(k, k)
            if isinstance(v, str) and v.strip().lower() in ("null", "none", "n/a", ""):
                v = None
            if isinstance(v, str):
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
            normalized_ac[canonical] = v
        data["analyst_consensus"] = normalized_ac
    elif ac is None or (isinstance(ac, str) and ac.strip().lower() in ("null", "none")):
        data["analyst_consensus"] = None

    # Ensure recent_news items are well-formed
    news = data.get("recent_news", [])
    if isinstance(news, list):
        cleaned = []
        for item in news:
            if isinstance(item, dict) and "headline" in item:
                item.setdefault("date", "unknown")
                item.setdefault("sentiment", "neutral")
                sent = str(item["sentiment"]).lower().strip()
                if sent not in ("positive", "negative", "neutral"):
                    item["sentiment"] = "neutral"
                cleaned.append(item)
        data["recent_news"] = cleaned if cleaned else [
            {"headline": f"Market data retrieved for {data.get('ticker', 'N/A')}", "date": "unknown", "sentiment": "neutral"}
        ]

    for field in ("current_price", "market_cap_billions", "week_52_high", "week_52_low"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = float(val)
            except ValueError:
                pass

    if not data.get("data_retrieval_timestamp"):
        data["data_retrieval_timestamp"] = datetime.now().isoformat()
    if not data.get("price_date"):
        data["price_date"] = data.get("data_retrieval_timestamp", datetime.now().isoformat())

    return data


def _normalize_fundamental(data: dict) -> dict:
    """Fix common Step 2 issues."""
    for dim in ("valuation", "growth", "moat", "balance_sheet"):
        obj = data.get(dim)
        if isinstance(obj, dict):
            evidence = obj.get("evidence", [])
            if isinstance(evidence, list):
                string_evidence = []
                for item in evidence:
                    if isinstance(item, str):
                        string_evidence.append(item)
                    elif isinstance(item, dict):
                        metric = item.get("metric", item.get("name", ""))
                        value = item.get("value", item.get("data", ""))
                        if metric:
                            string_evidence.append(f"{metric}: {value}" if value is not None else str(metric))
                        else:
                            string_evidence.append(str(item))
                    else:
                        string_evidence.append(str(item))
                obj["evidence"] = string_evidence if string_evidence else [obj.get("assessment", "No data available")]
            elif isinstance(evidence, str):
                obj["evidence"] = [evidence]
            else:
                obj["evidence"] = [obj.get("assessment", "No data available")]
            obj.setdefault("assessment", "N/A")
        elif isinstance(obj, str):
            data[dim] = {"assessment": obj, "evidence": [obj]}
        elif obj is None:
            data[dim] = {"assessment": "N/A", "evidence": ["No data available"]}

    rating = str(data.get("overall_fundamental_rating", "moderate")).lower().strip()
    if rating not in ("strong", "moderate", "weak"):
        rating = "moderate"
    data["overall_fundamental_rating"] = rating
    return data


def _normalize_technical(data: dict) -> dict:
    """Fix common Step 3 issues."""
    for field in ("support_levels", "resistance_levels"):
        val = data.get(field, [])
        if isinstance(val, (int, float)):
            data[field] = [val]
        elif isinstance(val, list):
            cleaned = []
            for v in val:
                if isinstance(v, (int, float)):
                    cleaned.append(float(v))
                elif isinstance(v, str):
                    try:
                        cleaned.append(float(v.replace("$", "").replace(",", "")))
                    except ValueError:
                        pass
            data[field] = cleaned if cleaned else [0.0]

    trend = str(data.get("current_trend", "consolidation")).lower().strip()
    if trend not in ("uptrend", "downtrend", "consolidation"):
        if "up" in trend or "bull" in trend:
            trend = "uptrend"
        elif "down" in trend or "bear" in trend:
            trend = "downtrend"
        else:
            trend = "consolidation"
    data["current_trend"] = trend

    rating = str(data.get("overall_technical_rating", "neutral")).lower().strip()
    if rating not in ("bullish", "neutral", "bearish"):
        if "bull" in rating or "positive" in rating:
            rating = "bullish"
        elif "bear" in rating or "negative" in rating:
            rating = "bearish"
        else:
            rating = "neutral"
    data["overall_technical_rating"] = rating

    rsi = data.get("rsi")
    if isinstance(rsi, str):
        try:
            rsi = float(rsi)
        except ValueError:
            rsi = None
    if isinstance(rsi, (int, float)):
        rsi = max(0, min(100, rsi))
    data["rsi"] = rsi

    return data


def _normalize_catalyst(data: dict) -> dict:
    """Fix common Step 4 issues."""
    for field in ("catalysts", "risks"):
        items = data.get(field, [])
        if not isinstance(items, list):
            items = [items] if items else []
        cleaned = []
        for item in items:
            if isinstance(item, str):
                item = {"event": item, "impact": "positive" if field == "catalysts" else "negative", "magnitude": "medium"}
            if isinstance(item, dict):
                item.setdefault("event", "Unknown")
                item.setdefault("impact", "positive" if field == "catalysts" else "negative")
                item.setdefault("magnitude", "medium")
                imp = str(item["impact"]).lower().strip()
                item["impact"] = imp if imp in ("positive", "negative") else ("positive" if field == "catalysts" else "negative")
                mag = str(item["magnitude"]).lower().strip()
                item["magnitude"] = mag if mag in ("high", "medium", "low") else "medium"
                cleaned.append(item)
        if not cleaned:
            default_event = "Market conditions" if field == "catalysts" else "Market risk"
            cleaned = [{"event": default_event, "impact": "positive" if field == "catalysts" else "negative", "magnitude": "medium"}]
        data[field] = cleaned
    return data


def _normalize_recommendation(data: dict) -> dict:
    """Fix common Step 5a issues."""
    rec = str(data.get("recommendation", "hold")).lower().strip()
    if rec not in ("buy", "hold", "sell", "avoid"):
        if "buy" in rec:
            rec = "buy"
        elif "sell" in rec:
            rec = "sell"
        elif "avoid" in rec:
            rec = "avoid"
        else:
            rec = "hold"
    data["recommendation"] = rec

    conf = data.get("confidence")
    if isinstance(conf, str):
        try:
            conf = float(conf.replace("%", ""))
            if conf > 1:
                conf = conf / 100.0
        except ValueError:
            conf = 0.5
    if isinstance(conf, (int, float)):
        conf = max(0.0, min(1.0, float(conf)))
    else:
        conf = 0.5
    data["confidence"] = conf

    ep = data.get("entry_price")
    if isinstance(ep, (int, float)):
        data["entry_price"] = {"ideal": float(ep), "acceptable_range": [float(ep) * 0.95, float(ep) * 1.05]}
    elif isinstance(ep, dict):
        if "ideal" not in ep and "price" in ep:
            ep["ideal"] = ep.pop("price")
        if "acceptable_range" not in ep or not isinstance(ep.get("acceptable_range"), list):
            ideal = float(ep.get("ideal", 0))
            ep["acceptable_range"] = [round(ideal * 0.95, 2), round(ideal * 1.05, 2)]

    tp = data.get("target_price")
    if isinstance(tp, (int, float)):
        data["target_price"] = {"conservative": float(tp) * 0.85, "base": float(tp), "optimistic": float(tp) * 1.15}
    elif isinstance(tp, dict):
        for alias, canonical in [("low", "conservative"), ("mid", "base"), ("high", "optimistic"),
                                  ("bear", "conservative"), ("bull", "optimistic"), ("target", "base")]:
            if alias in tp and canonical not in tp:
                tp[canonical] = tp.pop(alias)

    return data


# --- Normalizers for worker schemas ---


def _normalize_news_worker(data: dict) -> dict:
    """Normalize Worker 1a output."""
    headlines = data.get("headlines", [])
    if not isinstance(headlines, list):
        headlines = [headlines] if headlines else []
    cleaned = []
    for item in headlines:
        if isinstance(item, str):
            item = {"headline": item, "date": "unknown", "sentiment": "neutral"}
        if isinstance(item, dict) and "headline" in item:
            item.setdefault("date", "unknown")
            item.setdefault("sentiment", "neutral")
            sent = str(item["sentiment"]).lower().strip()
            if sent not in ("positive", "negative", "neutral"):
                item["sentiment"] = "neutral"
            cleaned.append(item)
    data["headlines"] = cleaned if cleaned else [
        {"headline": "No recent news available", "date": "unknown", "sentiment": "neutral"}
    ]
    return data


def _normalize_analyst_worker(data: dict) -> dict:
    """Normalize Worker 1b output."""
    alias_map = {
        "buy_ratings": "buy_count", "buys": "buy_count", "buy": "buy_count",
        "hold_ratings": "hold_count", "holds": "hold_count", "hold": "hold_count",
        "sell_ratings": "sell_count", "sells": "sell_count", "sell": "sell_count",
        "target_price": "average_target_price", "avg_target": "average_target_price",
        "avg_target_price": "average_target_price", "consensus_target": "average_target_price",
        "mean_target_price": "average_target_price",
    }
    normalized = {}
    for k, v in data.items():
        canonical = alias_map.get(k, k)
        if isinstance(v, str) and v.strip().lower() in ("null", "none", "n/a", ""):
            v = None
        if isinstance(v, str):
            try:
                v = float(v) if "." in v else int(v)
            except ValueError:
                pass
        # Don't let an alias overwrite a canonical key that was already set directly
        if canonical in normalized and k in alias_map:
            continue
        normalized[canonical] = v
    return normalized


def _normalize_dimension_worker(data: dict) -> dict:
    """Normalize Workers 2a-2d output (evidence dict->string conversion)."""
    evidence = data.get("evidence", [])
    if isinstance(evidence, list):
        string_evidence = []
        for item in evidence:
            if isinstance(item, str):
                string_evidence.append(item)
            elif isinstance(item, dict):
                metric = item.get("metric", item.get("name", ""))
                value = item.get("value", item.get("data", ""))
                if metric:
                    string_evidence.append(f"{metric}: {value}" if value is not None else str(metric))
                else:
                    string_evidence.append(str(item))
            else:
                string_evidence.append(str(item))
        data["evidence"] = string_evidence if string_evidence else [data.get("assessment", "No data")]
    elif isinstance(evidence, str):
        data["evidence"] = [evidence]
    else:
        data["evidence"] = [data.get("assessment", "No data")]
    data.setdefault("assessment", "N/A")
    return data


def _normalize_tech_interpretation(data: dict) -> dict:
    """Normalize Worker 3a output."""
    trend = str(data.get("current_trend", "consolidation")).lower().strip()
    if trend not in ("uptrend", "downtrend", "consolidation"):
        if "up" in trend or "bull" in trend:
            trend = "uptrend"
        elif "down" in trend or "bear" in trend:
            trend = "downtrend"
        else:
            trend = "consolidation"
    data["current_trend"] = trend

    rating = str(data.get("overall_technical_rating", "neutral")).lower().strip()
    if rating not in ("bullish", "neutral", "bearish"):
        if "bull" in rating or "positive" in rating:
            rating = "bullish"
        elif "bear" in rating or "negative" in rating:
            rating = "bearish"
        else:
            rating = "neutral"
    data["overall_technical_rating"] = rating

    data.setdefault("volume_analysis", "No volume data available")
    return data


def _normalize_catalyst_worker(data: dict) -> dict:
    """Normalize Worker 3b output."""
    items = data.get("catalysts", [])
    if not isinstance(items, list):
        items = [items] if items else []
    cleaned = []
    for item in items:
        if isinstance(item, str):
            item = {"event": item, "impact": "positive", "magnitude": "medium"}
        if isinstance(item, dict):
            item.setdefault("event", "Unknown catalyst")
            item.setdefault("impact", "positive")
            item.setdefault("magnitude", "medium")
            mag = str(item["magnitude"]).lower().strip()
            item["magnitude"] = mag if mag in ("high", "medium", "low") else "medium"
            item["impact"] = "positive"
            cleaned.append(item)
    data["catalysts"] = cleaned if cleaned else [
        {"event": "Market conditions", "impact": "positive", "magnitude": "medium"}
    ]
    return data


def _normalize_risk_worker(data: dict) -> dict:
    """Normalize Worker 3c output."""
    items = data.get("risks", [])
    if not isinstance(items, list):
        items = [items] if items else []
    cleaned = []
    for item in items:
        if isinstance(item, str):
            item = {"event": item, "impact": "negative", "magnitude": "medium"}
        if isinstance(item, dict):
            item.setdefault("event", "Unknown risk")
            item.setdefault("impact", "negative")
            item.setdefault("magnitude", "medium")
            mag = str(item["magnitude"]).lower().strip()
            item["magnitude"] = mag if mag in ("high", "medium", "low") else "medium"
            item["impact"] = "negative"
            cleaned.append(item)
    data["risks"] = cleaned if cleaned else [
        {"event": "Market risk", "impact": "negative", "magnitude": "medium"}
    ]
    return data


# ── LLM Step Runner ───────────────────────────────────────────────────────────


def run_step(adapter, system_prompt: str, user_prompt: str, schema_class, step_name: str) -> dict:
    """Run a single pipeline step with validation and retry."""
    schema = get_schema_dict(schema_class)
    prompt_hash = hashlib.md5(user_prompt.encode()).hexdigest()[:8]

    for attempt in range(3):
        try:
            result = adapter.complete_json(system_prompt, user_prompt, schema)
            log_llm_call(step_name, adapter.get_model_name(), adapter.last_usage, prompt_hash)

            # Normalize before validation (fixes common small-model mistakes)
            result = _normalize_output(result, schema_class)

            # Validate against schema
            validated = schema_class.model_validate(result)
            return validated.model_dump()

        except (ValidationError, ValueError, TypeError, KeyError) as e:
            logger.warning(f"  [{step_name}] Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                logger.info(f"  [{step_name}] Retrying...")
            else:
                raise RuntimeError(f"Step {step_name} failed after 3 attempts: {e}")


# ── Phase 0: Deterministic Data Gathering ─────────────────────────────────────


def _build_data_gathering_base(market_data: dict) -> dict:
    """Build DataGatheringOutput base from yfinance data. No LLM needed.

    News and analyst consensus are left empty — filled by Phase 1 workers.
    """
    return {
        "ticker": market_data["ticker"],
        "current_price": market_data.get("current_price") or 0.01,
        "price_date": market_data.get("data_timestamp", datetime.now().isoformat()),
        "pe_ratio": market_data.get("pe_ratio"),
        "forward_pe": market_data.get("forward_pe"),
        "ps_ratio": market_data.get("ps_ratio"),
        "market_cap_billions": market_data.get("market_cap_billions") or 0.01,
        "week_52_high": market_data.get("week_52_high") or 0.01,
        "week_52_low": market_data.get("week_52_low") or 0.01,
        "beta": market_data.get("beta"),
        "short_interest_pct": market_data.get("short_interest_pct"),
        "recent_news": [],  # Filled by Worker 1a
        "next_earnings_date": market_data.get("next_earnings_date"),
        "analyst_consensus": None,  # Filled by Worker 1b
        "data_retrieval_timestamp": market_data.get("data_timestamp", datetime.now().isoformat()),
    }


def _default_tech_indicators(current_price: float) -> dict:
    """Fallback technical indicators when no price history is available."""
    return {
        "rsi": None, "rsi_signal": "neutral",
        "macd_line": 0, "macd_signal": 0, "macd_histogram": 0, "macd_direction": "neutral",
        "sma_50": None, "sma_200": None,
        "price_vs_50_sma": "unknown", "price_vs_200_sma": "unknown",
        "golden_cross": False,
        "bollinger_upper": None, "bollinger_middle": None, "bollinger_lower": None,
        "bollinger_bandwidth": None, "bollinger_pct_b": None,
        "trend": "consolidation",
        "volume_avg_5d": 0, "volume_avg_30d": 0, "volume_ratio": 1.0,
        "volume_assessment": "No volume data available",
        "support_candidates": [round(current_price * 0.95, 2)],
        "resistance_candidates": [round(current_price * 1.05, 2)],
    }


def _compute_price_zones(current_price: float, tech: dict, time_horizon: str = "medium") -> dict:
    """Compute stop / entry / target zones from technical indicators.

    Returns a dict of named price levels for use by step5a prompt and assembly.
    Every level is evidence-based (derived from MAs, Bollinger, pivots).

    Entry zone width varies by time horizon:
      short:  ±1% — "should I buy NOW at this price?"
      medium: ±3% — small pullback acceptable
      long:   ±5% — can wait for a better price (limit order)

    Zone structure:
      stop_zone:    [candidate levels below entry — where to place stops]
      entry_zone:   [low, high] — reasonable range around current price
      target_zone:  [candidate levels above entry — where to take profits]

    Each candidate is a (price, label) tuple so the LLM knows WHY a level matters.
    """
    supports = tech.get("support_candidates", [])
    resistances = tech.get("resistance_candidates", [])
    sma_50 = tech.get("sma_50")
    sma_200 = tech.get("sma_200")
    bb_upper = tech.get("bollinger_upper")
    bb_lower = tech.get("bollinger_lower")
    bb_middle = tech.get("bollinger_middle")

    # --- Stop zone: levels below current price ---
    stop_candidates = []
    for s in supports:
        if s < current_price:
            stop_candidates.append((round(s, 2), "pivot support"))
    if bb_lower and bb_lower < current_price:
        stop_candidates.append((round(bb_lower, 2), "Bollinger lower band"))
    if sma_50 and sma_50 < current_price:
        stop_candidates.append((round(sma_50, 2), "50-day SMA"))
    if sma_200 and sma_200 < current_price:
        stop_candidates.append((round(sma_200, 2), "200-day SMA"))
    # Deduplicate (within $0.50) and sort descending (nearest first)
    stop_candidates = _dedup_levels(stop_candidates, tolerance=0.5)
    stop_candidates.sort(key=lambda x: x[0], reverse=True)

    # --- Target zone: levels above current price ---
    target_candidates = []
    for r in resistances:
        if r > current_price:
            target_candidates.append((round(r, 2), "pivot resistance"))
    if bb_upper and bb_upper > current_price:
        target_candidates.append((round(bb_upper, 2), "Bollinger upper band"))
    if sma_50 and sma_50 > current_price:
        target_candidates.append((round(sma_50, 2), "50-day SMA"))
    if sma_200 and sma_200 > current_price:
        target_candidates.append((round(sma_200, 2), "200-day SMA"))
    # Deduplicate and sort ascending (nearest first)
    target_candidates = _dedup_levels(target_candidates, tolerance=0.5)
    target_candidates.sort(key=lambda x: x[0])

    # --- Entry zone: range around current price, width depends on time horizon ---
    # Short: you're asking "buy NOW?" → entry ≈ current price (±1%)
    # Medium: small pullback acceptable (±3%)
    # Long: can wait for better price via limit order (±5%, anchored to MA/BB)
    entry_clamp = {"short": 0.01, "medium": 0.03, "long": 0.05}
    clamp_pct = entry_clamp.get(time_horizon, 0.03)

    if time_horizon == "long":
        # Long horizon: use technical anchor (MA/BB) for entry zone
        anchors = [a for a in [bb_middle, sma_50] if a is not None]
        anchor = sum(anchors) / len(anchors) if anchors else current_price
        raw_low = min(current_price, anchor) * 0.98
        raw_high = max(current_price, anchor) * 1.02
    else:
        # Short/medium: center on current price
        raw_low = current_price * (1 - clamp_pct)
        raw_high = current_price * (1 + clamp_pct)

    # Final clamp
    entry_low = round(max(raw_low, current_price * (1 - clamp_pct)), 2)
    entry_high = round(min(raw_high, current_price * (1 + clamp_pct)), 2)

    # Fallback: if no tech candidates, synthesize from current price
    if not stop_candidates:
        stop_candidates = [(round(current_price * 0.93, 2), "7% below (fallback)")]
    if not target_candidates:
        target_candidates = [(round(current_price * 1.10, 2), "10% above (fallback)")]

    return {
        "stop_zone": stop_candidates,       # [(price, label), ...] descending
        "entry_zone": [entry_low, entry_high],
        "target_zone": target_candidates,    # [(price, label), ...] ascending
    }


def _dedup_levels(candidates: list[tuple[float, str]], tolerance: float = 0.5) -> list[tuple[float, str]]:
    """Remove near-duplicate price levels, keeping the first (highest priority) label."""
    if not candidates:
        return []
    # Sort by price for dedup
    sorted_c = sorted(candidates, key=lambda x: x[0])
    result = [sorted_c[0]]
    for price, label in sorted_c[1:]:
        if abs(price - result[-1][0]) > tolerance:
            result.append((price, label))
    return result


# ── Phase 1-3: Parallel Worker Prompt Building ───────────────────────────────


def _build_worker_prompts(
    step1_base: dict, market_data: dict, tech_indicators: dict, risk_profile
) -> dict:
    """Build all 9 worker prompts from Phase 0 data.

    Returns: {worker_name: (prompt_text, schema_class)}
    """
    ticker = step1_base["ticker"]
    current_price = step1_base["current_price"]
    company_name = market_data.get("company_name", ticker)

    workers = {}

    # Worker 1a: News
    workers["1a_news"] = (
        _fill_prompt(
            load_prompt("worker_1a_news.md"),
            ticker=ticker,
            company_name=company_name,
        ),
        NewsWorkerOutput,
    )

    # Worker 1b: Analyst consensus
    workers["1b_analyst"] = (
        _fill_prompt(
            load_prompt("worker_1b_analyst.md"),
            ticker=ticker,
            current_price=current_price,
        ),
        AnalystWorkerOutput,
    )

    # Worker 2a: Valuation
    workers["2a_valuation"] = (
        _fill_prompt(
            load_prompt("worker_2a_valuation.md"),
            ticker=ticker,
            current_price=current_price,
            pe_ratio=market_data.get("pe_ratio", "N/A"),
            forward_pe=market_data.get("forward_pe", "N/A"),
            ps_ratio=market_data.get("ps_ratio", "N/A"),
            market_cap_billions=market_data.get("market_cap_billions", "N/A"),
            week_52_high=market_data.get("week_52_high", "N/A"),
            week_52_low=market_data.get("week_52_low", "N/A"),
            sector=market_data.get("sector", "Unknown"),
        ),
        DimensionWorkerOutput,
    )

    # Worker 2b: Growth
    workers["2b_growth"] = (
        _fill_prompt(
            load_prompt("worker_2b_growth.md"),
            ticker=ticker,
            revenue_growth=_format_pct(market_data.get("revenue_growth")),
            earnings_growth=_format_pct(market_data.get("earnings_growth")),
            sector=market_data.get("sector", "Unknown"),
            industry=market_data.get("industry", "Unknown"),
        ),
        DimensionWorkerOutput,
    )

    # Worker 2c: Moat
    workers["2c_moat"] = (
        _fill_prompt(
            load_prompt("worker_2c_moat.md"),
            ticker=ticker,
            company_name=company_name,
            sector=market_data.get("sector", "Unknown"),
            industry=market_data.get("industry", "Unknown"),
            profit_margins=_format_pct(market_data.get("profit_margins")),
            revenue_growth=_format_pct(market_data.get("revenue_growth")),
        ),
        DimensionWorkerOutput,
    )

    # Worker 2d: Balance sheet
    workers["2d_balance"] = (
        _fill_prompt(
            load_prompt("worker_2d_balance.md"),
            ticker=ticker,
            total_debt=_format_money(market_data.get("total_debt")),
            total_cash=_format_money(market_data.get("total_cash")),
            free_cash_flow=_format_money(market_data.get("free_cash_flow")),
            profit_margins=_format_pct(market_data.get("profit_margins")),
            dividend_yield=_format_pct(market_data.get("dividend_yield")),
        ),
        DimensionWorkerOutput,
    )

    # Worker 3a: Technical interpretation
    workers["3a_technical"] = (
        _fill_prompt(
            load_prompt("worker_3a_technical.md"),
            ticker=ticker,
            current_price=current_price,
            rsi=tech_indicators.get("rsi", "N/A"),
            rsi_signal=tech_indicators.get("rsi_signal", "neutral"),
            macd_direction=tech_indicators.get("macd_direction", "neutral"),
            macd_histogram=tech_indicators.get("macd_histogram", 0),
            trend=tech_indicators.get("trend", "consolidation"),
            sma_50=tech_indicators.get("sma_50", "N/A"),
            sma_200=tech_indicators.get("sma_200", "N/A"),
            price_vs_50_sma=tech_indicators.get("price_vs_50_sma", "unknown"),
            price_vs_200_sma=tech_indicators.get("price_vs_200_sma", "unknown"),
            golden_cross=tech_indicators.get("golden_cross", False),
            bollinger_upper=tech_indicators.get("bollinger_upper", "N/A"),
            bollinger_middle=tech_indicators.get("bollinger_middle", "N/A"),
            bollinger_lower=tech_indicators.get("bollinger_lower", "N/A"),
            bollinger_pct_b=tech_indicators.get("bollinger_pct_b", "N/A"),
            volume_assessment=tech_indicators.get("volume_assessment", "N/A"),
            volume_ratio=tech_indicators.get("volume_ratio", 1.0),
        ),
        TechInterpretationOutput,
    )

    # Worker 3b: Catalysts
    workers["3b_catalysts"] = (
        _fill_prompt(
            load_prompt("worker_3b_catalysts.md"),
            ticker=ticker,
            company_name=company_name,
            sector=market_data.get("sector", "Unknown"),
            industry=market_data.get("industry", "Unknown"),
            next_earnings_date=step1_base.get("next_earnings_date", "unknown"),
        ),
        CatalystWorkerOutput,
    )

    # Worker 3c: Risks
    workers["3c_risks"] = (
        _fill_prompt(
            load_prompt("worker_3c_risks.md"),
            ticker=ticker,
            company_name=company_name,
            sector=market_data.get("sector", "Unknown"),
            industry=market_data.get("industry", "Unknown"),
            current_price=current_price,
            market_cap_billions=market_data.get("market_cap_billions", "N/A"),
        ),
        RiskWorkerOutput,
    )

    return workers


def _run_step_with_stats(adapter, system_prompt, user_prompt, schema_class, step_name):
    """Run a step and return (result, usage_stats) for stats collection."""
    result = run_step(adapter, system_prompt, user_prompt, schema_class, step_name)
    return result, adapter.last_usage.copy()


def _run_parallel_workers(
    adapter, system_prompt: str, worker_defs: dict, max_workers: int = 4
) -> tuple:
    """Run all Phase 1-3 workers in parallel using ThreadPoolExecutor.

    Args:
        adapter: LLM adapter (will be cloned per worker for thread safety).
        system_prompt: System prompt for all workers.
        worker_defs: {name: (prompt_text, schema_class)} from _build_worker_prompts.
        max_workers: Max concurrent threads.

    Returns:
        ({worker_name: result_dict}, {worker_name: usage_dict})
    """
    results = {}
    worker_stats = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for name, (prompt, schema_class) in worker_defs.items():
            worker_adapter = _clone_adapter(adapter)
            future = pool.submit(
                _run_step_with_stats, worker_adapter, system_prompt, prompt, schema_class, f"Worker {name}"
            )
            futures[future] = (name, worker_adapter)

        for future in as_completed(futures):
            name, w_adapter = futures[future]
            try:
                result, usage = future.result()
                results[name] = result
                worker_stats[name] = usage
            except Exception as e:
                logger.error(f"  [Worker {name}] FAILED: {e}")
                results[name] = None
                worker_stats[name] = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "error": str(e)}

    return results, worker_stats


# ── Dry-Run Worker Loading ────────────────────────────────────────────────────


def _load_dry_run_workers(ticker: str) -> dict:
    """Split existing fixtures into worker-format data for dry run.

    Reuses crwd_step1-step4 fixtures, splitting them into per-worker results.
    """
    step1 = _load_mock(ticker, "step1")
    step2 = _load_mock(ticker, "step2")
    step3 = _load_mock(ticker, "step3")
    step4 = _load_mock(ticker, "step4")

    return {
        "1a_news": {"headlines": step1.get("recent_news", [])},
        "1b_analyst": step1.get("analyst_consensus") or {
            "average_target_price": None, "buy_count": 0, "hold_count": 0, "sell_count": 0
        },
        "2a_valuation": step2.get("valuation", {"assessment": "N/A", "evidence": ["No data"]}),
        "2b_growth": step2.get("growth", {"assessment": "N/A", "evidence": ["No data"]}),
        "2c_moat": step2.get("moat", {"assessment": "N/A", "evidence": ["No data"]}),
        "2d_balance": step2.get("balance_sheet", {"assessment": "N/A", "evidence": ["No data"]}),
        "3a_technical": {
            "current_trend": step3.get("current_trend", "consolidation"),
            "overall_technical_rating": step3.get("overall_technical_rating", "neutral"),
            "volume_analysis": step3.get("volume_analysis", "No volume data available"),
        },
        "3b_catalysts": {"catalysts": step4.get("catalysts", [])},
        "3c_risks": {"risks": step4.get("risks", [])},
    }


# ── Phase Assembly Functions ──────────────────────────────────────────────────


def _assemble_step1(base: dict, worker_results: dict) -> dict:
    """Merge Phase 0 base data with Worker 1a/1b results -> DataGatheringOutput."""
    step1 = base.copy()

    # Worker 1a: news headlines
    news_result = worker_results.get("1a_news")
    if news_result and "headlines" in news_result:
        step1["recent_news"] = news_result["headlines"]

    # Worker 1b: analyst consensus
    analyst_result = worker_results.get("1b_analyst")
    if analyst_result:
        step1["analyst_consensus"] = analyst_result

    # Ensure required fields
    if not step1["recent_news"]:
        step1["recent_news"] = [
            {"headline": f"Market data retrieved for {step1['ticker']}", "date": "unknown", "sentiment": "neutral"}
        ]

    return step1


def _assemble_step2(ticker: str, worker_results: dict) -> dict:
    """Assemble FundamentalAnalysisOutput from Workers 2a-2d."""
    val = worker_results.get("2a_valuation") or {"assessment": "N/A", "evidence": ["No data"]}
    growth = worker_results.get("2b_growth") or {"assessment": "N/A", "evidence": ["No data"]}
    moat = worker_results.get("2c_moat") or {"assessment": "N/A", "evidence": ["No data"]}
    bs = worker_results.get("2d_balance") or {"assessment": "N/A", "evidence": ["No data"]}

    rating = _compute_fundamental_rating(val, growth, moat, bs)

    return {
        "ticker": ticker,
        "valuation": val,
        "growth": growth,
        "moat": moat,
        "balance_sheet": bs,
        "overall_fundamental_rating": rating,
    }


def _assemble_step3(ticker: str, tech_indicators: dict, worker_results: dict) -> dict:
    """Assemble TechnicalAnalysisOutput from Phase 0 indicators + Worker 3a."""
    interp = worker_results.get("3a_technical") or {}

    return {
        "ticker": ticker,
        "current_trend": interp.get("current_trend", tech_indicators.get("trend", "consolidation")),
        "support_levels": tech_indicators.get("support_candidates", [0.0]),
        "resistance_levels": tech_indicators.get("resistance_candidates", [0.0]),
        "rsi": tech_indicators.get("rsi"),
        "rsi_signal": tech_indicators.get("rsi_signal"),
        "macd_direction": tech_indicators.get("macd_direction"),
        "volume_analysis": interp.get("volume_analysis", tech_indicators.get("volume_assessment", "No data")),
        "overall_technical_rating": interp.get("overall_technical_rating", "neutral"),
    }


def _assemble_step4(ticker: str, worker_results: dict, concentration: dict) -> dict:
    """Assemble CatalystRiskOutput from Workers 3b/3c + concentration."""
    catalysts_result = worker_results.get("3b_catalysts") or {}
    risks_result = worker_results.get("3c_risks") or {}

    catalysts = catalysts_result.get("catalysts", [
        {"event": "Market conditions", "impact": "positive", "magnitude": "medium"}
    ])
    risks = risks_result.get("risks", [
        {"event": "Market risk", "impact": "negative", "magnitude": "medium"}
    ])

    return {
        "ticker": ticker,
        "catalysts": catalysts,
        "risks": risks,
        "correlation_with_holdings": concentration.get("correlation_with_holdings"),
        "concentration_risk_flag": concentration.get("concentration_risk_flag", False),
    }


def _compute_fundamental_rating(val: dict, growth: dict, moat: dict, bs: dict) -> str:
    """Compute overall fundamental rating from dimension assessments (deterministic).

    Uses word-boundary regex matching to prevent substring false positives
    (e.g., "not strong" won't match "strong", "consolidated" won't match "solid").
    """
    import re

    POSITIVE = [
        "strong", "healthy", "wide moat", "accelerating", "robust", "excellent",
        "solid", "impressive", "favorable", "premium justified", "expanding",
        "high-growth", "net cash", "low debt",
    ]
    NEGATIVE = [
        "weak", "declining", "decelerating", "unhealthy", "concerning", "poor",
        "narrow moat", "overvalued", "deteriorating", "challenged", "fragile",
        "expensive", "high debt",
    ]

    # Build word-boundary patterns; also reject if preceded by "not "
    def _has_keyword(text: str, keywords: list[str]) -> bool:
        for kw in keywords:
            pattern = rf"(?<!\bnot\s)\b{re.escape(kw)}\b"
            if re.search(pattern, text):
                return True
        return False

    score = 0
    for dim in [val, growth, moat, bs]:
        text = dim.get("assessment", "").lower()
        has_pos = _has_keyword(text, POSITIVE)
        has_neg = _has_keyword(text, NEGATIVE)
        if has_pos and not has_neg:
            score += 1
        elif has_neg and not has_pos:
            score -= 1
        # Mixed or neutral: score += 0

    if score >= 2:
        return "strong"
    elif score <= -2:
        return "weak"
    return "moderate"


# ── Phase 5: Deterministic Assembly ───────────────────────────────────────────


def _build_exit_strategy(
    entry: float, stop: float, targets: dict, time_horizon: str
) -> list[dict]:
    """Build tiered exit strategy from existing price levels + time horizon.

    Short:  limited upside window → exit all at base target, take what you can.
    Medium: moderate room → scale out gradually across all three targets.
    Long:   trend is your friend → lock partial profits early, let the rest ride.

    All tiers include a hard stop-loss as the first tier.
    """
    tiers = []

    # Tier 0: Hard stop (all horizons)
    tiers.append({
        "price": stop,
        "action": "stop_loss",
        "sell_pct": 100,
        "move_stop_to": None,
        "note": "Hard stop — full exit",
    })

    if time_horizon == "short":
        # Short: limited window — exit all at base target
        tiers.append({
            "price": targets["base"],
            "action": "take_profit",
            "sell_pct": 100,
            "move_stop_to": None,
            "note": "Full exit at base target — short horizon, take what you can",
        })

    elif time_horizon == "long":
        # Long: lock partial early, let the rest ride to optimistic
        tiers.append({
            "price": targets["conservative"],
            "action": "take_profit",
            "sell_pct": 33,
            "move_stop_to": round(entry, 2),
            "note": "Lock 1/3 at conservative target, move stop to breakeven",
        })
        tiers.append({
            "price": targets["base"],
            "action": "take_profit",
            "sell_pct": 50,
            "move_stop_to": round(targets["conservative"], 2),
            "note": "Take half remaining at base target, trail stop up",
        })
        tiers.append({
            "price": targets["optimistic"],
            "action": "take_profit",
            "sell_pct": 100,
            "move_stop_to": None,
            "note": "Close position at optimistic target — long trend paid off",
        })

    else:
        # Medium (default): balanced scale-out, exit at base
        tiers.append({
            "price": targets["conservative"],
            "action": "take_profit",
            "sell_pct": 50,
            "move_stop_to": round(entry, 2),
            "note": "Lock half at conservative target, move stop to breakeven",
        })
        tiers.append({
            "price": targets["base"],
            "action": "take_profit",
            "sell_pct": 100,
            "move_stop_to": None,
            "note": "Close remaining at base target",
        })

    return tiers


def _snap_to_nearest(price: float, candidates: list[tuple[float, str]], direction: str = "any") -> float:
    """Snap a price to the nearest candidate level.

    direction: "above" = only snap to levels >= price, "below" = only levels <= price, "any" = closest.
    Returns the original price if no candidates match.
    """
    filtered = candidates
    if direction == "above":
        filtered = [(p, l) for p, l in candidates if p >= price * 0.98]  # allow 2% tolerance
    elif direction == "below":
        filtered = [(p, l) for p, l in candidates if p <= price * 1.02]
    if not filtered:
        return price
    closest = min(filtered, key=lambda x: abs(x[0] - price))
    return closest[0]


def _assemble_decision(
    rec: dict, narrative: dict, risk_profile: RiskProfile, data: dict,
    price_zones: dict | None = None,
    fundamental_rating: str = "moderate",
) -> dict:
    """Phase 5: Assemble final DecisionOutput with deterministic math.

    Validates LLM-provided prices against technical zones, snaps to nearest
    technical levels when the LLM deviates, computes R:R, position size, and
    exit strategy.

    LLM reasoning feeds into code math via:
      - confidence → scales position size (high conviction = bigger bet)
      - fundamental_rating → shifts base target (strong = lean optimistic)
    """
    entry = rec["entry_price"]["ideal"]
    stop = rec["stop_loss"]
    position_usd = rec["position_size_recommended_usd"]
    targets = rec["target_price"]
    current_price = data.get("current_price", entry)
    confidence = rec.get("confidence", 0.5)

    # Short horizon: entry must be at/near current price (the question is "buy NOW?")
    # Medium: allow small deviation (±3%)
    # Long: trust the LLM's entry from the wider zone
    entry_max_deviation = {"short": 0.01, "medium": 0.03, "long": 0.05}
    max_dev = entry_max_deviation.get(risk_profile.time_horizon, 0.03)
    if abs(entry - current_price) / current_price > max_dev:
        old_entry = entry
        entry = current_price
        rec["entry_price"]["ideal"] = entry
        rec["entry_price"]["acceptable_range"] = [
            round(current_price * (1 - max_dev), 2),
            round(current_price * (1 + max_dev), 2),
        ]
        logger.info(
            f"  [Phase 5] Entry ${old_entry:.2f} too far from current ${current_price:.2f} "
            f"for {risk_profile.time_horizon} horizon — reset to ${entry:.2f}"
        )

    # ── Position sizing: risk tolerance sets ceiling, confidence scales within it ──
    # High confidence (0.9) → use 90% of ceiling → bigger bet
    # Low confidence (0.4) → use 40% of ceiling → smaller bet
    # Floor at 25% so we never recommend a trivially small position
    max_pct = {"conservative": 0.50, "moderate": 0.75, "aggressive": 1.0}
    base_pct = max_pct.get(risk_profile.risk_tolerance, 0.75)
    confidence_factor = max(0.25, min(1.0, confidence))
    effective_pct = base_pct * confidence_factor
    max_usd = risk_profile.position_size_usd * effective_pct
    position_usd = min(position_usd, max_usd, risk_profile.position_size_usd)
    logger.info(
        f"  [Phase 5] Position sizing: {risk_profile.risk_tolerance} ceiling {base_pct:.0%} "
        f"× {confidence:.0%} confidence = {effective_pct:.0%} → ${position_usd:,.0f}"
    )

    # --- Assign prices from technical zones (zones are the ground truth) ---
    if price_zones:
        stop_cands = price_zones["stop_zone"]
        target_cands = price_zones["target_zone"]

        # Stop: pick nearest support level below entry
        if stop_cands:
            below_entry = [(p, l) for p, l in stop_cands if p < entry]
            if below_entry:
                old_stop = stop
                # Prefer the closest support to the LLM's suggested stop
                stop = _snap_to_nearest(stop, below_entry, direction="any")
                if abs(stop - old_stop) > 0.01:
                    logger.info(f"  [Phase 5] Snapped stop ${old_stop:.2f} → ${stop:.2f} (nearest technical support)")

        # Targets: assign from zone levels above entry (code-driven, not LLM-driven)
        # Conservative and optimistic are always the zone boundaries.
        # Base target shifts by fundamental strength:
        #   strong → lean optimistic (67% of range) — fundamentals support higher prices
        #   moderate → midpoint (50% of range)
        #   weak → lean conservative (33% of range) — take profits earlier
        if target_cands:
            above_entry = sorted([(p, l) for p, l in target_cands if p > entry], key=lambda x: x[0])
            fundamental_blend = {"strong": 0.67, "moderate": 0.50, "weak": 0.33}
            blend = fundamental_blend.get(fundamental_rating, 0.50)

            if len(above_entry) >= 2:
                targets["conservative"] = above_entry[0][0]
                targets["optimistic"] = above_entry[-1][0]
                # Base: blend between conservative and optimistic, shifted by fundamentals
                targets["base"] = round(
                    targets["conservative"] + blend * (targets["optimistic"] - targets["conservative"]), 2
                )
            elif len(above_entry) == 1:
                # 1 level: use as anchor, interpolate around it
                level = above_entry[0][0]
                targets["conservative"] = round(entry + (level - entry) * 0.50, 2)
                targets["base"] = level
                targets["optimistic"] = round(level + (level - entry) * 0.50, 2)

            logger.info(
                f"  [Phase 5] Targets from zones (fundamental={fundamental_rating}, blend={blend:.0%}): "
                f"cons=${targets['conservative']:.2f}, base=${targets['base']:.2f}, opt=${targets['optimistic']:.2f}"
            )

    # Guard 1: stop must be below entry
    denominator = entry - stop
    if denominator <= 0:
        stop = round(entry * 0.93, 2)
        denominator = entry - stop

    # Guard 2: hard cap as safety net (technical snapping should handle most cases)
    max_upside = {"short": 1.50, "medium": 2.00, "long": 3.00}
    cap_multiplier = max_upside.get(risk_profile.time_horizon, 2.00)
    max_target = round(current_price * cap_multiplier, 2)
    if targets["optimistic"] > max_target:
        logger.warning(
            f"  [Phase 5] Clamped optimistic target from ${targets['optimistic']:.2f} "
            f"to ${max_target:.2f} ({risk_profile.time_horizon} horizon cap)"
        )
        targets["optimistic"] = max_target
    if targets["base"] > max_target:
        targets["base"] = round(entry + (max_target - entry) * 0.67, 2)
    if targets["conservative"] > targets["base"]:
        targets["conservative"] = round(entry + (targets["base"] - entry) * 0.50, 2)

    # Ensure ordering after snapping/clamping
    if targets["conservative"] >= targets["base"]:
        targets["conservative"] = round(entry + (targets["base"] - entry) * 0.5, 2)
    if targets["base"] >= targets["optimistic"]:
        targets["optimistic"] = round(targets["base"] * 1.15, 2)

    # Guard 3: R:R computed from (snapped) base target
    numerator = targets["base"] - entry
    if numerator <= 0:
        numerator = denominator * 0.5
    risk_reward = max(0.01, round(numerator / denominator, 2))

    # Compute position size percentage (deterministic)
    position_pct = round(position_usd / risk_profile.position_size_usd, 2)

    # Build tiered exit strategy (only for buy/hold — sell/avoid don't need profit tiers)
    recommendation = rec["recommendation"]
    if recommendation in ("buy", "hold"):
        exit_strategy = _build_exit_strategy(entry, stop, targets, risk_profile.time_horizon)
    else:
        exit_strategy = []

    return {
        "ticker": rec["ticker"],
        "recommendation": rec["recommendation"],
        "confidence": rec["confidence"],
        "entry_price": rec["entry_price"],
        "target_price": targets,
        "stop_loss": stop,
        "position_size_recommended_usd": position_usd,
        "position_size_pct_of_input": position_pct,
        "time_horizon": risk_profile.time_horizon,
        "risk_reward_ratio": risk_reward,
        "exit_strategy": exit_strategy,
        "key_conditions": narrative["key_conditions"],
        "bull_case_summary": narrative["bull_case_summary"],
        "bear_case_summary": narrative["bear_case_summary"],
        "one_line_summary": narrative["one_line_summary"],
    }


# ── Mock Data Loading ─────────────────────────────────────────────────────────


def _load_mock(ticker: str, step: str) -> dict:
    """Load mock step results for dry run."""
    mock_path = MOCK_DIR / f"{ticker.lower()}_{step}.json"
    if mock_path.exists():
        with open(mock_path) as f:
            return json.load(f)
    raise FileNotFoundError(f"Mock data not found: {mock_path}")


class _DryRunAdapter:
    """Stub adapter for dry-run mode that never calls an API."""

    def __init__(self, model_name: str = "dry-run"):
        self._model = model_name
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    def get_model_name(self) -> str:
        return self._model


# ── Main Pipeline ─────────────────────────────────────────────────────────────


def run_pipeline(
    ticker: str,
    risk_profile: RiskProfile,
    adapter,
    dry_run: bool = False,
) -> tuple:
    """Run the full analysis pipeline (Swarm Architecture).

    Phase 0:   Deterministic data gathering (yfinance parse, tech indicators, concentration)
    Phase 1-3: 9 parallel LLM workers (news, analyst, 4x fundamental, tech, catalysts, risks)
    Phase 4:   2 sequential LLM workers (recommendation, narratives)
    Phase 5:   Deterministic assembly (math, clamping, validation)

    Returns:
        (AnalysisResult, pipeline_stats_dict)
    """
    config = load_config()
    system_prompt = load_prompt("system.md")
    max_workers = config.get("workflow", {}).get("max_workers", 4)
    pipeline_stats = {"workers": {}, "phase4": {}}

    # ── Phase 0: Deterministic Data Gathering ──────────────────────────────

    logger.info("Phase 0: Deterministic data gathering...")

    if dry_run:
        mock_path = MOCK_DIR / f"{ticker.lower()}_market_data.json"
        if mock_path.exists():
            with open(mock_path) as f:
                market_data = json.load(f)
            logger.info(f"  [Phase 0] Loaded mock market data from {mock_path}")
        else:
            raise FileNotFoundError(f"Mock data not found: {mock_path}")
        hist = None
    else:
        market_data, hist = fetch_market_data(ticker)

    # Phase 0a: Build DataGatheringOutput base from yfinance (no LLM)
    step1_base = _build_data_gathering_base(market_data)
    current_price = step1_base["current_price"]
    logger.info(f"  [Phase 0a] Built data base: {ticker} @ ${current_price}")

    # Phase 0b: Compute technical indicators from price history
    if hist is not None and not hist.empty:
        from workflow.indicators import build_technical_indicators
        tech_indicators = build_technical_indicators(hist, current_price)
        logger.info(f"  [Phase 0b] Technical indicators: RSI={tech_indicators.get('rsi')}, "
                     f"trend={tech_indicators.get('trend')}, MACD={tech_indicators.get('macd_direction')}")
    elif dry_run:
        try:
            phase0_path = MOCK_DIR / f"{ticker.lower()}_phase0_technical.json"
            with open(phase0_path) as f:
                tech_indicators = json.load(f)
            logger.info(f"  [Phase 0b] Loaded mock technical indicators from {phase0_path}")
        except FileNotFoundError:
            tech_indicators = _default_tech_indicators(current_price)
            logger.info("  [Phase 0b] Using default technical indicators (no fixture found)")
    else:
        tech_indicators = _default_tech_indicators(current_price)
        logger.info("  [Phase 0b] Using default technical indicators (no history)")

    # Phase 0c: Sector concentration check (deterministic)
    from workflow.concentration import check_sector_concentration, check_sector_concentration_from_cache

    if dry_run:
        sector_map = {"NVDA": "Technology", "AAPL": "Technology", "TSLA": "Consumer Cyclical",
                      "MSFT": "Technology", "GOOG": "Communication Services", "META": "Communication Services",
                      "AMZN": "Consumer Cyclical", "AMD": "Technology", "INTC": "Technology"}
        concentration = check_sector_concentration_from_cache(
            ticker, market_data.get("sector", "Unknown"),
            risk_profile.existing_holdings, sector_map,
        )
    else:
        concentration = check_sector_concentration(
            ticker, market_data.get("sector", "Unknown"),
            risk_profile.existing_holdings,
        )
    logger.info(f"  [Phase 0c] Concentration risk: {concentration['concentration_risk_flag']}")

    # ── Phase 1-3: Parallel LLM Workers ────────────────────────────────────

    if dry_run:
        logger.info("Phase 1-3: Loading dry-run worker fixtures...")
        worker_results = _load_dry_run_workers(ticker)
        worker_stats = {name: {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0} for name in worker_results}
    else:
        logger.info(f"Phase 1-3: Running 9 parallel workers (max_workers={max_workers})...")
        worker_prompts = _build_worker_prompts(step1_base, market_data, tech_indicators, risk_profile)
        worker_results, worker_stats = _run_parallel_workers(adapter, system_prompt, worker_prompts, max_workers)

    pipeline_stats["workers"] = worker_stats

    # Log worker completion summary
    succeeded = sum(1 for v in worker_results.values() if v is not None)
    failed = sum(1 for v in worker_results.values() if v is None)
    logger.info(f"  [Phase 1-3] Workers completed: {succeeded} succeeded, {failed} failed")

    # ── Assemble intermediate results ──────────────────────────────────────

    logger.info("Assembling intermediate results...")
    step1_result = _assemble_step1(step1_base, worker_results)
    step2_result = _assemble_step2(ticker, worker_results)
    step3_result = _assemble_step3(ticker, tech_indicators, worker_results)
    step4_result = _assemble_step4(ticker, worker_results, concentration)

    # ── Phase 4: Sequential LLM (Recommendation + Narratives) ─────────────

    # Build compact summaries for Phase 4 prompts (include date + magnitude)
    catalyst_items = step4_result.get("catalysts", [])
    risk_items = step4_result.get("risks", [])

    def _summarize_item(item: dict) -> str:
        parts = [item.get("event", "")[:80]]
        date = item.get("expected_date")
        if date and date != "unknown":
            parts.append(f"({date})")
        mag = item.get("magnitude")
        if mag:
            parts.append(f"[{mag}]")
        return " ".join(parts)

    catalyst_summary = "; ".join(_summarize_item(c) for c in catalyst_items[:4])
    risk_summary = "; ".join(_summarize_item(r) for r in risk_items[:4])

    # Summarize all 4 fundamental dimensions (not just valuation)
    valuation_summary = step2_result.get("valuation", {}).get("assessment", "N/A")
    growth_summary = step2_result.get("growth", {}).get("assessment", "N/A")
    moat_summary = step2_result.get("moat", {}).get("assessment", "N/A")
    balance_sheet_summary = step2_result.get("balance_sheet", {}).get("assessment", "N/A")

    # Summarize analyst consensus for step5a/5b
    ac = step1_result.get("analyst_consensus")
    if ac and isinstance(ac, dict):
        parts = []
        tp = ac.get("average_target_price")
        if tp:
            parts.append(f"Avg target: ${tp:.2f}")
        buy = ac.get("buy_count", 0)
        hold = ac.get("hold_count", 0)
        sell = ac.get("sell_count", 0)
        if buy or hold or sell:
            parts.append(f"Ratings: {buy} buy / {hold} hold / {sell} sell")
        analyst_consensus_summary = " | ".join(parts) if parts else "No analyst consensus data"
    else:
        analyst_consensus_summary = "No analyst consensus data"

    # Compute price zones from technical indicators (deterministic)
    price_zones = _compute_price_zones(current_price, tech_indicators, risk_profile.time_horizon)
    logger.info(
        f"  [Phase 4] Price zones: stops={[p for p, _ in price_zones['stop_zone']]}, "
        f"entry={price_zones['entry_zone']}, targets={[p for p, _ in price_zones['target_zone']]}"
    )

    # Format zones as readable text for the prompt
    stop_zone_text = "\n".join(f"- ${p:.2f} ({label})" for p, label in price_zones["stop_zone"]) or "- No technical levels found"
    entry_zone_text = f"${price_zones['entry_zone'][0]:.2f} – ${price_zones['entry_zone'][1]:.2f}"
    target_zone_text = "\n".join(f"- ${p:.2f} ({label})" for p, label in price_zones["target_zone"]) or "- No technical levels found"

    # Worker 4a: Recommendation & Price Levels
    logger.info("Phase 4a: Recommendation & Price Levels...")
    step5a_prompt = load_prompt("step5a_recommendation.md")
    step5a_prompt = _fill_prompt(
        step5a_prompt,
        ticker=ticker,
        risk_tolerance=risk_profile.risk_tolerance,
        time_horizon=risk_profile.time_horizon,
        position_size_usd=str(risk_profile.position_size_usd),
        existing_holdings=", ".join(risk_profile.existing_holdings) if risk_profile.existing_holdings else "None",
        current_price=str(step1_result.get("current_price", 0)),
        fundamental_rating=step2_result.get("overall_fundamental_rating", "unknown"),
        valuation_summary=valuation_summary,
        growth_summary=growth_summary,
        moat_summary=moat_summary,
        balance_sheet_summary=balance_sheet_summary,
        analyst_consensus_summary=analyst_consensus_summary,
        technical_rating=step3_result.get("overall_technical_rating", "unknown"),
        support_levels=str(step3_result.get("support_levels", [])),
        resistance_levels=str(step3_result.get("resistance_levels", [])),
        current_trend=step3_result.get("current_trend", "unknown"),
        catalyst_summary=catalyst_summary,
        risk_summary=risk_summary,
        concentration_risk=str(step4_result.get("concentration_risk_flag", False)),
        stop_zone=stop_zone_text,
        entry_zone=entry_zone_text,
        target_zone=target_zone_text,
    )

    if dry_run:
        step5a_result = _load_mock(ticker, "step5a")
        pipeline_stats["phase4"]["4a_recommendation"] = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    else:
        step5a_result = run_step(adapter, system_prompt, step5a_prompt, RecommendationOutput, "Phase 4a")
        pipeline_stats["phase4"]["4a_recommendation"] = adapter.last_usage.copy()

    # Worker 4b: Narratives
    logger.info("Phase 4b: Conditions & Narratives...")
    step5b_prompt = load_prompt("step5b_narrative.md")
    step5b_prompt = _fill_prompt(
        step5b_prompt,
        ticker=ticker,
        recommendation=step5a_result.get("recommendation", "hold"),
        confidence=str(step5a_result.get("confidence", 0.5)),
        entry_price=str(step5a_result.get("entry_price", {}).get("ideal", 0)),
        target_base=str(step5a_result.get("target_price", {}).get("base", 0)),
        stop_loss=str(step5a_result.get("stop_loss", 0)),
        position_size=str(step5a_result.get("position_size_recommended_usd", 0)),
        fundamental_rating=step2_result.get("overall_fundamental_rating", "unknown"),
        valuation_summary=valuation_summary,
        growth_summary=growth_summary,
        moat_summary=moat_summary,
        balance_sheet_summary=balance_sheet_summary,
        technical_rating=step3_result.get("overall_technical_rating", "unknown"),
        support_levels=str(step3_result.get("support_levels", [])),
        catalyst_summary=catalyst_summary,
        risk_summary=risk_summary,
        analyst_consensus_summary=analyst_consensus_summary,
        concentration_risk=str(step4_result.get("concentration_risk_flag", False)),
        existing_holdings=", ".join(risk_profile.existing_holdings) if risk_profile.existing_holdings else "None",
    )

    if dry_run:
        step5b_result = _load_mock(ticker, "step5b")
        pipeline_stats["phase4"]["4b_narrative"] = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
    else:
        step5b_result = run_step(adapter, system_prompt, step5b_prompt, NarrativeOutput, "Phase 4b")
        pipeline_stats["phase4"]["4b_narrative"] = adapter.last_usage.copy()

    # ── Phase 5: Deterministic Post-Processing ─────────────────────────────

    logger.info("Phase 5: Deterministic post-processing...")
    fund_rating = step2_result.get("overall_fundamental_rating", "moderate")
    step5_result = _assemble_decision(step5a_result, step5b_result, risk_profile, step1_result, price_zones, fund_rating)

    # ── Final Result Assembly ──────────────────────────────────────────────

    result = AnalysisResult(
        ticker=ticker,
        risk_profile=risk_profile,
        model_name=adapter.get_model_name(),
        timestamp=datetime.now().isoformat(),
        step1_data=DataGatheringOutput.model_validate(step1_result),
        step2_fundamental=FundamentalAnalysisOutput.model_validate(step2_result),
        step3_technical=TechnicalAnalysisOutput.model_validate(step3_result),
        step4_catalysts=CatalystRiskOutput.model_validate(step4_result),
        step5_decision=DecisionOutput.model_validate(step5_result),
    )

    # Finalize pipeline stats
    pipeline_stats["phase0"] = {
        "current_price": current_price,
        "rsi": tech_indicators.get("rsi"),
        "rsi_signal": tech_indicators.get("rsi_signal"),
        "macd_direction": tech_indicators.get("macd_direction"),
        "trend": tech_indicators.get("trend"),
        "support_levels": tech_indicators.get("support_candidates", []),
        "resistance_levels": tech_indicators.get("resistance_candidates", []),
        "bollinger_upper": tech_indicators.get("bollinger_upper"),
        "bollinger_lower": tech_indicators.get("bollinger_lower"),
        "bollinger_bandwidth": tech_indicators.get("bollinger_bandwidth"),
        "concentration_risk": concentration.get("concentration_risk_flag", False),
        "price_zones": {
            "stop_zone": [(p, l) for p, l in price_zones["stop_zone"]],
            "entry_zone": price_zones["entry_zone"],
            "target_zone": [(p, l) for p, l in price_zones["target_zone"]],
        },
    }
    pipeline_stats["fundamental_rating"] = step2_result.get("overall_fundamental_rating", "unknown")
    pipeline_stats["technical_rating"] = step3_result.get("overall_technical_rating", "unknown")
    pipeline_stats["workers_succeeded"] = succeeded
    pipeline_stats["workers_failed"] = failed

    all_usage = list(pipeline_stats["workers"].values()) + list(pipeline_stats["phase4"].values())
    pipeline_stats["total_llm_calls"] = len([u for u in all_usage if u.get("input_tokens", 0) > 0])
    pipeline_stats["total_tokens_in"] = sum(u.get("input_tokens", 0) for u in all_usage)
    pipeline_stats["total_tokens_out"] = sum(u.get("output_tokens", 0) for u in all_usage)

    return result, pipeline_stats


# ── Feedback Loop (Critique-and-Revise) ───────────────────────────────────────


def _build_feedback_brief(eval_report, iteration: int) -> str:
    """Extract judge failures into a structured feedback brief for Phase 4 re-run.

    Improvements over naive approach:
    1. Prioritizes by dimension weight × judge consensus (high-impact first)
    2. Caps actionable feedback to top 6 items (prevents small-model overwhelm)
    3. Excludes data-gap items entirely (they can't be fixed, just noise)
    4. Includes "keep what works" section to prevent regression
    """
    from workflow.schema import DIMENSION_SUB_ITEMS

    DIMENSION_WEIGHTS = {
        "causal_reasoning": 0.25,
        "information_completeness": 0.25,
        "actionability": 0.20,
        "risk_awareness": 0.20,
        "user_appropriateness": 0.10,
    }

    # Sub-items that come from Phase 1-3 workers (data, not synthesis)
    # These CANNOT be fixed by re-running Phase 4 — exclude from feedback
    DATA_PHASE_ITEMS = {"news_substantive", "catalyst_variety", "risk_variety", "diverse_risk_categories"}
    # Sub-items that come from Phase 4a (recommendation / price levels)
    PHASE_4A_ITEMS = {
        "technical_alignment", "recommendation_follows_evidence", "confidence_calibrated",
        "entry_range_justified", "targets_tiered_and_realistic", "stop_loss_technical_basis",
        "position_size_appropriate", "time_horizon_matched",
    }
    # Everything else maps to Phase 4b (narrative)

    # Build sub-item → dimension mapping for weight lookup
    sub_to_dim: dict[str, str] = {}
    for dim_name, items in DIMENSION_SUB_ITEMS.items():
        for item in items:
            sub_to_dim[item] = dim_name

    pool = eval_report.layer2_pool
    judges = pool.individual_results if pool else ([eval_report.layer2] if eval_report.layer2 else [])
    if not judges:
        return ""
    num_judges = len(judges)

    # Collect failures AND passes across all judges
    failures: dict[str, list[str]] = {}  # sub_item_name -> [note1, ...]
    passes: set[str] = set()  # sub-items that passed in ALL judges

    all_sub_items: dict[str, dict] = {}  # track per sub-item: {met_count, fail_count}
    for judge in judges:
        for dim_name in DIMENSION_SUB_ITEMS:
            dim_score = getattr(judge, dim_name, None)
            if dim_score is None or dim_score.sub_items is None:
                continue
            for sub_name, sub_result in dim_score.sub_items.items():
                if sub_name not in all_sub_items:
                    all_sub_items[sub_name] = {"met": 0, "fail": 0}
                if sub_result.met:
                    all_sub_items[sub_name]["met"] += 1
                else:
                    all_sub_items[sub_name]["fail"] += 1
                    failures.setdefault(sub_name, []).append(sub_result.note)

    # Items passing unanimously → "keep what works" list
    for sub_name, counts in all_sub_items.items():
        if counts["fail"] == 0 and sub_name not in DATA_PHASE_ITEMS:
            passes.add(sub_name)

    # Filter out data-gap items (can't fix by re-running Phase 4)
    actionable_failures = {k: v for k, v in failures.items() if k not in DATA_PHASE_ITEMS}
    data_gap_count = sum(1 for k in failures if k in DATA_PHASE_ITEMS)

    if not actionable_failures:
        return ""

    # Prioritize by: dimension_weight × (fail_count / num_judges)
    # This ranks high-weight dimension failures with strong consensus first
    scored_failures = []
    for sub_name, notes in actionable_failures.items():
        dim_name = sub_to_dim.get(sub_name, "")
        weight = DIMENSION_WEIGHTS.get(dim_name, 0.1)
        consensus = len(notes) / num_judges  # 1.0 = all judges flagged
        priority = weight * consensus
        best_note = max(notes, key=len) if notes else ""
        phase = "4a" if sub_name in PHASE_4A_ITEMS else "4b"
        scored_failures.append((priority, len(notes), sub_name, best_note, phase))

    # Sort by priority descending, then by consensus count
    scored_failures.sort(key=lambda x: (-x[0], -x[1]))

    # Cap to top 6 actionable items (prevent small-model overwhelm)
    MAX_FEEDBACK_ITEMS = 6
    top_failures = scored_failures[:MAX_FEEDBACK_ITEMS]
    dropped_count = len(scored_failures) - len(top_failures)

    # Build feedback brief
    phase4a_issues = []
    phase4b_issues = []
    for _priority, count, sub_name, note, phase in top_failures:
        line = f"- **{sub_name}**: \"{note}\" ({count}/{num_judges} judges flagged)"
        if phase == "4a":
            phase4a_issues.append(line)
        else:
            phase4b_issues.append(line)

    lines = [f"## Judge Feedback (Iteration {iteration} — {len(actionable_failures)} fixable failures)\n"]

    if phase4a_issues:
        lines.append("### FIX these in your Recommendation (price levels / sizing):")
        lines.extend(phase4a_issues)
        lines.append("")

    if phase4b_issues:
        lines.append("### FIX these in your Narrative (conditions / summaries):")
        lines.extend(phase4b_issues)
        lines.append("")

    if dropped_count > 0:
        lines.append(f"({dropped_count} lower-priority issues omitted — focus on the above first)")
        lines.append("")

    if data_gap_count > 0:
        lines.append(f"Note: {data_gap_count} data-gap issues exist (limited news/catalysts/risks) — "
                      "these cannot be fixed, do not try to compensate for missing data.")
        lines.append("")

    # "Keep what works" — prevent regression on passing items
    if passes:
        # Group by phase for clarity
        keep_4a = sorted(p for p in passes if p in PHASE_4A_ITEMS)
        keep_4b = sorted(p for p in passes if p not in PHASE_4A_ITEMS)
        keep_items = keep_4a + keep_4b
        if len(keep_items) > 8:
            # Don't overwhelm — just show count
            lines.append(f"**KEEP UNCHANGED**: {len(keep_items)} items are passing — "
                          "do NOT change aspects that are already working.")
        else:
            lines.append(f"**KEEP UNCHANGED** (these are passing — do NOT break them):")
            for item in keep_items:
                lines.append(f"- {item} ✓")
        lines.append("")

    lines.append("**Focus on the specific failures above. Do not rewrite everything — "
                  "make targeted fixes only.**")

    return "\n".join(lines)


def _rerun_phase4(
    adapter,
    system_prompt: str,
    feedback_brief: str,
    step1_result: dict,
    step2_result: dict,
    step3_result: dict,
    step4_result: dict,
    risk_profile: RiskProfile,
    tech_indicators: dict,
    price_zones: dict,
    prev_result: AnalysisResult,
    iteration: int,
) -> tuple[AnalysisResult, dict]:
    """Re-run Phase 4 (recommendation + narrative) with judge feedback injected.

    Reuses all Phase 0-3 data. Only re-runs the 2 LLM calls + deterministic assembly.
    Returns: (new_result, phase4_stats)
    """
    ticker = prev_result.ticker
    current_price = step1_result.get("current_price", 0)

    # Build summaries (same as original — recompute from existing step results)
    valuation_summary = step2_result.get("valuation", {}).get("assessment", "N/A")
    growth_summary = step2_result.get("growth", {}).get("assessment", "N/A")
    moat_summary = step2_result.get("moat", {}).get("assessment", "N/A")
    balance_sheet_summary = step2_result.get("balance_sheet", {}).get("assessment", "N/A")

    ac = step1_result.get("analyst_consensus")
    if ac and isinstance(ac, dict):
        parts = []
        tp = ac.get("average_target_price")
        if tp:
            parts.append(f"Avg target: ${tp:.2f}")
        buy = ac.get("buy_count", 0)
        hold = ac.get("hold_count", 0)
        sell = ac.get("sell_count", 0)
        if buy or hold or sell:
            parts.append(f"Ratings: {buy} buy / {hold} hold / {sell} sell")
        analyst_consensus_summary = " | ".join(parts) if parts else "No analyst consensus data"
    else:
        analyst_consensus_summary = "No analyst consensus data"

    catalyst_list = step4_result.get("catalysts", [])
    risk_list = step4_result.get("risks", [])
    catalyst_summary = "; ".join(
        f"{c['event']} ({c.get('expected_date', 'TBD')}, {c['magnitude']})"
        for c in catalyst_list[:3]
    ) if catalyst_list else "None identified"
    risk_summary = "; ".join(
        f"{r['event']} ({r['magnitude']})" for r in risk_list[:3]
    ) if risk_list else "None identified"

    # Format zones
    stop_zone_text = "\n".join(f"- ${p:.2f} ({label})" for p, label in price_zones["stop_zone"]) or "- No technical levels found"
    entry_zone_text = f"${price_zones['entry_zone'][0]:.2f} – ${price_zones['entry_zone'][1]:.2f}"
    target_zone_text = "\n".join(f"- ${p:.2f} ({label})" for p, label in price_zones["target_zone"]) or "- No technical levels found"

    # Phase 4a: Recommendation + feedback
    logger.info(f"  [Iteration {iteration}] Re-running Phase 4a with judge feedback...")
    step5a_prompt = load_prompt("step5a_recommendation.md")
    step5a_prompt = _fill_prompt(
        step5a_prompt,
        ticker=ticker,
        risk_tolerance=risk_profile.risk_tolerance,
        time_horizon=risk_profile.time_horizon,
        position_size_usd=str(risk_profile.position_size_usd),
        existing_holdings=", ".join(risk_profile.existing_holdings) if risk_profile.existing_holdings else "None",
        current_price=str(current_price),
        fundamental_rating=step2_result.get("overall_fundamental_rating", "unknown"),
        valuation_summary=valuation_summary,
        growth_summary=growth_summary,
        moat_summary=moat_summary,
        balance_sheet_summary=balance_sheet_summary,
        analyst_consensus_summary=analyst_consensus_summary,
        technical_rating=step3_result.get("overall_technical_rating", "unknown"),
        support_levels=str(step3_result.get("support_levels", [])),
        resistance_levels=str(step3_result.get("resistance_levels", [])),
        current_trend=step3_result.get("current_trend", "unknown"),
        catalyst_summary=catalyst_summary,
        risk_summary=risk_summary,
        concentration_risk=str(step4_result.get("concentration_risk_flag", False)),
        stop_zone=stop_zone_text,
        entry_zone=entry_zone_text,
        target_zone=target_zone_text,
    )
    step5a_prompt += f"\n\n{feedback_brief}"
    step5a_result = run_step(adapter, system_prompt, step5a_prompt, RecommendationOutput, f"Iter{iteration}-4a")
    phase4_stats = {"4a_recommendation": adapter.last_usage.copy()}

    # Phase 4b: Narrative + feedback
    logger.info(f"  [Iteration {iteration}] Re-running Phase 4b with judge feedback...")
    step5b_prompt = load_prompt("step5b_narrative.md")
    step5b_prompt = _fill_prompt(
        step5b_prompt,
        ticker=ticker,
        recommendation=step5a_result.get("recommendation", "hold"),
        confidence=str(step5a_result.get("confidence", 0.5)),
        entry_price=str(step5a_result.get("entry_price", {}).get("ideal", 0)),
        target_base=str(step5a_result.get("target_price", {}).get("base", 0)),
        stop_loss=str(step5a_result.get("stop_loss", 0)),
        position_size=str(step5a_result.get("position_size_recommended_usd", 0)),
        fundamental_rating=step2_result.get("overall_fundamental_rating", "unknown"),
        valuation_summary=valuation_summary,
        growth_summary=growth_summary,
        moat_summary=moat_summary,
        balance_sheet_summary=balance_sheet_summary,
        technical_rating=step3_result.get("overall_technical_rating", "unknown"),
        support_levels=str(step3_result.get("support_levels", [])),
        catalyst_summary=catalyst_summary,
        risk_summary=risk_summary,
        analyst_consensus_summary=analyst_consensus_summary,
        concentration_risk=str(step4_result.get("concentration_risk_flag", False)),
        existing_holdings=", ".join(risk_profile.existing_holdings) if risk_profile.existing_holdings else "None",
    )
    step5b_prompt += f"\n\n{feedback_brief}"
    step5b_result = run_step(adapter, system_prompt, step5b_prompt, NarrativeOutput, f"Iter{iteration}-4b")
    phase4_stats["4b_narrative"] = adapter.last_usage.copy()

    # Phase 5: Re-assemble
    fund_rating = step2_result.get("overall_fundamental_rating", "moderate")
    step5_result = _assemble_decision(step5a_result, step5b_result, risk_profile, step1_result, price_zones, fund_rating)

    # Build new AnalysisResult (same Phase 0-3, new Phase 4-5)
    new_result = AnalysisResult(
        ticker=ticker,
        risk_profile=risk_profile,
        model_name=adapter.get_model_name(),
        timestamp=datetime.now().isoformat(),
        step1_data=prev_result.step1_data,
        step2_fundamental=prev_result.step2_fundamental,
        step3_technical=prev_result.step3_technical,
        step4_catalysts=prev_result.step4_catalysts,
        step5_decision=DecisionOutput.model_validate(step5_result),
    )

    return new_result, phase4_stats


def run_pipeline_with_feedback(
    ticker: str,
    risk_profile: RiskProfile,
    adapter,
    config: dict,
    max_iterations: int = 1,
    dry_run: bool = False,
) -> tuple[AnalysisResult, dict, object, list]:
    """Run pipeline with optional judge feedback loop.

    Returns: (result, pipeline_stats, eval_report, iteration_history)
    iteration_history is a list of dicts: [{iteration, score, failures, passed}, ...]
    """
    from eval.run_eval import run_eval

    # Iteration 0: full pipeline
    result, pipeline_stats = run_pipeline(ticker, risk_profile, adapter, dry_run=dry_run)
    iteration_history = []

    if dry_run or max_iterations <= 1:
        # No feedback loop — run eval once and return
        eval_report = run_eval(result, config)
        score = eval_report.layer2_pool.overall_weighted_average if eval_report.layer2_pool else (
            eval_report.layer2.overall_weighted_average if eval_report.layer2 else 0
        )
        iteration_history.append({
            "iteration": 0, "score": score, "passed": eval_report.overall_passed,
            "failures": _count_failures(eval_report),
        })
        return result, pipeline_stats, eval_report, iteration_history

    # Extract intermediate step results for re-runs
    step1_result = result.step1_data.model_dump()
    step2_result = result.step2_fundamental.model_dump()
    step3_result = result.step3_technical.model_dump()
    step4_result = result.step4_catalysts.model_dump()

    # Retrieve tech_indicators and price_zones from pipeline_stats
    p0 = pipeline_stats.get("phase0", {})
    tech_indicators = {
        "support_candidates": p0.get("support_levels", []),
        "resistance_candidates": p0.get("resistance_levels", []),
        "sma_50": None,  # Not stored in stats; price zones already computed
        "sma_200": None,
        "bollinger_upper": p0.get("bollinger_upper"),
        "bollinger_lower": p0.get("bollinger_lower"),
        "bollinger_middle": None,
    }
    price_zones = p0.get("price_zones", {})
    # Reconstruct tuples from serialized lists
    if price_zones:
        price_zones = {
            "stop_zone": [(p, l) for p, l in price_zones.get("stop_zone", [])],
            "entry_zone": price_zones.get("entry_zone", [0, 0]),
            "target_zone": [(p, l) for p, l in price_zones.get("target_zone", [])],
        }

    system_prompt = "You are an expert financial analyst."

    # Track best result across iterations — always return the highest-scoring one
    best_result = result
    best_eval = None
    best_score = -1.0
    best_iteration = -1
    prev_score = None
    last_rerun_iteration = 0  # tracks how many re-runs we actually did

    for iteration in range(1, max_iterations):
        # Evaluate current result (which is from iteration-1)
        logger.info(f"  [Feedback] Evaluating iteration {iteration - 1}...")
        eval_report = run_eval(result, config)
        score = eval_report.layer2_pool.overall_weighted_average if eval_report.layer2_pool else (
            eval_report.layer2.overall_weighted_average if eval_report.layer2 else 0
        )
        num_failures = _count_failures(eval_report)
        iteration_history.append({
            "iteration": iteration - 1, "score": score, "passed": eval_report.overall_passed,
            "failures": num_failures,
        })

        # Track best result
        if score > best_score:
            best_score = score
            best_result = result
            best_eval = eval_report
            best_iteration = iteration - 1

        if eval_report.overall_passed:
            logger.info(f"  [Feedback] PASSED at iteration {iteration - 1} (score: {score:.2f}/5.0)")

        # Convergence detection: stop if score regressed from previous iteration
        if prev_score is not None and score < prev_score - 0.05:
            logger.warning(
                f"  [Feedback] Score regressed ({prev_score:.2f} → {score:.2f}), "
                f"stopping early — best is iteration {best_iteration} ({best_score:.2f})"
            )
            break

        prev_score = score

        # Build feedback and re-run Phase 4
        # Even if passed, keep iterating — might get a higher score
        feedback_brief = _build_feedback_brief(eval_report, iteration)
        if not feedback_brief:
            logger.info("  [Feedback] No actionable failures — nothing left to improve")
            break

        logger.info(
            f"  [Feedback] Iteration {iteration}: {num_failures} failures, "
            f"score {score:.2f}/5.0 — re-running Phase 4..."
        )
        result, phase4_stats = _rerun_phase4(
            adapter, system_prompt, feedback_brief,
            step1_result, step2_result, step3_result, step4_result,
            risk_profile, tech_indicators, price_zones,
            result, iteration,
        )
        pipeline_stats.setdefault("feedback_iterations", []).append(phase4_stats)
        last_rerun_iteration = iteration
    else:
        # Loop completed without break — need to eval the final re-run
        if last_rerun_iteration > 0:
            logger.info(f"  [Feedback] Evaluating iteration {last_rerun_iteration}...")
            eval_report = run_eval(result, config)
            score = eval_report.layer2_pool.overall_weighted_average if eval_report.layer2_pool else (
                eval_report.layer2.overall_weighted_average if eval_report.layer2 else 0
            )
            iteration_history.append({
                "iteration": last_rerun_iteration, "score": score, "passed": eval_report.overall_passed,
                "failures": _count_failures(eval_report),
            })
            if score > best_score:
                best_score = score
                best_result = result
                best_eval = eval_report
                best_iteration = last_rerun_iteration

    # Return best result across all iterations
    result = best_result
    eval_report = best_eval

    status = "PASSED" if eval_report.overall_passed else "FAILED"
    total_iters = len(iteration_history)
    logger.info(
        f"  [Feedback] Done: {status} — best iteration {best_iteration} "
        f"(score: {best_score:.2f}/5.0) out of {total_iters} evaluated"
    )

    return result, pipeline_stats, eval_report, iteration_history


def _count_failures(eval_report) -> int:
    """Count total sub-item failures across all judges."""
    from workflow.schema import DIMENSION_SUB_ITEMS
    pool = eval_report.layer2_pool
    judges = pool.individual_results if pool else ([eval_report.layer2] if eval_report.layer2 else [])
    if not judges:
        return 0

    # Count unique failing sub-items (failed by any judge)
    failed_items = set()
    for judge in judges:
        for dim_name in DIMENSION_SUB_ITEMS:
            dim_score = getattr(judge, dim_name, None)
            if dim_score is None or dim_score.sub_items is None:
                continue
            for sub_name, sub_result in dim_score.sub_items.items():
                if not sub_result.met:
                    failed_items.add(sub_name)
    return len(failed_items)


# ── Save & CLI ────────────────────────────────────────────────────────────────


def save_result(result: AnalysisResult) -> Path:
    """Save analysis result to results directory."""
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{result.ticker}_{result.model_name}_{timestamp}.json"
    filepath = RESULTS_DIR / filename
    with open(filepath, "w") as f:
        json.dump(result.model_dump(), f, indent=2, default=str)
    logger.info(f"Results saved to {filepath}")
    return filepath


def print_rich_summary(result: AnalysisResult, stats: dict, eval_report=None, iteration_history: list | None = None):
    """Print a comprehensive summary of the analysis run."""
    decision = result.step5_decision
    p0 = stats.get("phase0", {})
    W = 64

    # ANSI color codes for terminal output
    C_GREEN = "\033[32m"
    C_RED = "\033[31m"
    C_YELLOW = "\033[33m"
    C_CYAN = "\033[36m"
    C_DIM = "\033[2m"
    C_BOLD = "\033[1m"
    C_RESET = "\033[0m"

    print("\n" + "=" * W)
    print(f"  ANALYSIS COMPLETE: {result.ticker}  ({result.model_name})")
    print("=" * W)

    # ── Phase 0: Deterministic Data ──
    print(f"\n  {'-- Phase 0: Deterministic Data ':─<{W-2}}")
    rsi_val = p0.get("rsi")
    rsi_str = f"{rsi_val:.1f} ({p0.get('rsi_signal', 'N/A')})" if rsi_val is not None else "N/A"
    print(f"  Price: ${p0.get('current_price', 0):.2f}  |  RSI: {rsi_str}  |  MACD: {p0.get('macd_direction', 'N/A')}")
    print(f"  Trend: {p0.get('trend', 'N/A')}  |  Concentration risk: {'YES' if p0.get('concentration_risk') else 'no'}")
    supports = p0.get("support_levels", [])
    resistances = p0.get("resistance_levels", [])
    if supports:
        print(f"  Supports:    {', '.join(f'${s:.2f}' for s in supports[:3])}")
    if resistances:
        print(f"  Resistances: {', '.join(f'${r:.2f}' for r in resistances[:3])}")
    bb_upper = p0.get("bollinger_upper")
    bb_lower = p0.get("bollinger_lower")
    if bb_upper and bb_lower:
        print(f"  Bollinger:   ${bb_lower:.2f} – ${bb_upper:.2f} (bandwidth: {p0.get('bollinger_bandwidth', 'N/A')})")
    zones = p0.get("price_zones", {})
    if zones:
        tz = zones.get("target_zone", [])
        sz = zones.get("stop_zone", [])
        if tz:
            print(f"  Target zone: {', '.join(f'${p:.2f} ({l})' for p, l in tz[:4])}")
        if sz:
            print(f"  Stop zone:   {', '.join(f'${p:.2f} ({l})' for p, l in sz[:4])}")

    # ── Worker Breakdown ──
    worker_stats = stats.get("workers", {})
    phase4_stats = stats.get("phase4", {})
    has_real_stats = any(u.get("input_tokens", 0) > 0 for u in worker_stats.values())

    if has_real_stats:
        print(f"\n  {'-- Phase 1-3: Parallel Workers ':─<{W-2}}")
        print(f"  {'Worker':<20} {'Tok In':>7} {'Tok Out':>8} {'Latency':>9}")
        print(f"  {'─'*20} {'─'*7} {'─'*8} {'─'*9}")
        for name in sorted(worker_stats.keys()):
            u = worker_stats[name]
            if u.get("error"):
                print(f"  {name:<20} {'FAILED':>7} {'':>8} {'':>9}")
            else:
                lat = u.get("latency_ms", 0) / 1000
                print(f"  {name:<20} {u.get('input_tokens',0):>7,} {u.get('output_tokens',0):>8,} {lat:>8.1f}s")

        print(f"\n  {'-- Phase 4: Sequential Workers ':─<{W-2}}")
        for name in sorted(phase4_stats.keys()):
            u = phase4_stats[name]
            lat = u.get("latency_ms", 0) / 1000
            print(f"  {name:<20} {u.get('input_tokens',0):>7,} {u.get('output_tokens',0):>8,} {lat:>8.1f}s")

        total_in = stats.get("total_tokens_in", 0)
        total_out = stats.get("total_tokens_out", 0)
        print(f"\n  Total: {stats.get('total_llm_calls', 0)} LLM calls, "
              f"{total_in:,} tokens in, {total_out:,} tokens out")

    # ── Analysis Summary ──
    print(f"\n  {'-- Analysis Summary ':─<{W-2}}")
    print(f"  Fundamental: {stats.get('fundamental_rating', 'N/A')}  |  Technical: {stats.get('technical_rating', 'N/A')}")
    print(f"  Workers: {stats.get('workers_succeeded', 0)} succeeded, {stats.get('workers_failed', 0)} failed")

    # ── Decision ──
    print(f"\n  {'-- Decision ':─<{W-2}}")
    rec = decision.recommendation.upper()
    rec_color = C_GREEN if rec in ("BUY",) else (C_RED if rec in ("SELL", "AVOID") else C_YELLOW)
    print(f"  Recommendation: {rec_color}{C_BOLD}{rec}{C_RESET} ({decision.confidence:.0%} confidence)")
    print(f"  Entry: ${decision.entry_price.ideal:.2f}  |  Target: ${decision.target_price.base:.2f}  |  Stop: ${decision.stop_loss:.2f}")
    print(f"  Risk/Reward: {decision.risk_reward_ratio:.1f}x  |  Position: ${decision.position_size_recommended_usd:,.0f} ({decision.position_size_pct_of_input:.0%})")

    # ── Exit Strategy ──
    if decision.exit_strategy:
        horizon = result.risk_profile.time_horizon
        print(f"\n  {'-- Exit Strategy ':─<{W-2}}  {C_DIM}({horizon} horizon){C_RESET}")
        for tier in decision.exit_strategy:
            if tier.action == "stop_loss":
                action_str = f"{C_RED}STOP  {C_RESET}"
            else:
                action_str = f"{C_GREEN}PROFIT{C_RESET}"
            sell_str = f"sell {tier.sell_pct:>3}%"
            stop_str = ""
            if tier.move_stop_to is not None:
                stop_str = f"  {C_CYAN}stop→${tier.move_stop_to:.0f}{C_RESET}"
            print(f"  {C_BOLD}${tier.price:>9,.2f}{C_RESET}  {action_str}  {sell_str}{stop_str}")
            print(f"  {' ':>11}  {C_DIM}{tier.note}{C_RESET}")

    print(f"\n  {decision.one_line_summary}")

    # ── Eval Results ──
    if eval_report is not None:
        print(f"\n  {'-- Eval Results ':─<{W-2}}")
        l1 = eval_report.layer1
        status1_color = C_GREEN if l1.passed else C_RED
        status1 = "PASSED" if l1.passed else "FAILED"
        print(f"  L1 Deterministic: {l1.passed_checks}/{l1.total_checks} {status1_color}{status1}{C_RESET}")

        if not l1.passed:
            for name, check in l1.checks.items():
                if not check["passed"]:
                    print(f"     {C_RED}FAIL:{C_RESET} {name} — {C_DIM}{check['reason'][:60]}{C_RESET}")

        # Check for pool results first
        l2_pool = getattr(eval_report, "layer2_pool", None)

        if l2_pool:
            # Pool of judges display
            status2_color = C_GREEN if l2_pool.passed else C_RED
            status2 = "PASSED" if l2_pool.passed else "FAILED"
            print(f"  L2 Judge Pool:    {C_BOLD}{l2_pool.overall_weighted_average:.2f}/5.0{C_RESET} {status2_color}{status2}{C_RESET}")
            print(f"    Judges: {l2_pool.num_succeeded}/{l2_pool.num_judges} succeeded"
                  f"  |  Spread: {l2_pool.score_spread:.2f}")

            dims = [
                ("Causal Reasoning",        l2_pool.causal_reasoning),
                ("Information Completeness", l2_pool.information_completeness),
                ("Actionability",            l2_pool.actionability),
                ("Risk Awareness",           l2_pool.risk_awareness),
                ("User Appropriateness",     l2_pool.user_appropriateness),
            ]
            for name, dim in dims:
                score_color = C_GREEN if dim.mean_score >= 4.0 else (C_YELLOW if dim.mean_score >= 3.0 else C_RED)
                print(f"    {name:<25} {score_color}{dim.mean_score:.1f}/5{C_RESET}  {C_DIM}[{dim.min_score}-{dim.max_score}]{C_RESET}")

            # Per-judge breakdown with failed sub-items
            print(f"\n    {'-- Per-Judge Scores ':─<{W-4}}")
            for jr in l2_pool.individual_results:
                jr_color = C_GREEN if jr.passed else C_RED
                status = "PASS" if jr.passed else "FAIL"
                print(f"    {C_CYAN}{jr.judge_model}{C_RESET}: {jr.overall_weighted_average:.2f}/5.0 ({jr_color}{status}{C_RESET})")
                # Show failed sub-items with notes for quick diagnosis
                jr_dims = [
                    jr.causal_reasoning, jr.information_completeness,
                    jr.actionability, jr.risk_awareness, jr.user_appropriateness,
                ]
                failures = []
                for ddim in jr_dims:
                    if ddim.sub_items:
                        for item_name, item in ddim.sub_items.items():
                            if not item.met:
                                note = f": {C_DIM}{item.note}{C_RESET}" if item.note else ""
                                failures.append(f"      {C_RED}✗{C_RESET} {item_name}{note}")
                if failures:
                    for f in failures:
                        print(f)
        else:
            l2 = eval_report.layer2
            if l2:
                status2_color = C_GREEN if l2.passed else C_RED
                status2 = "PASSED" if l2.passed else "FAILED"
                print(f"  L2 LLM Judge:     {C_BOLD}{l2.overall_weighted_average:.2f}/5.0{C_RESET} {status2_color}{status2}{C_RESET}")
                dims = [
                    ("Causal Reasoning",        l2.causal_reasoning),
                    ("Information Completeness", l2.information_completeness),
                    ("Actionability",            l2.actionability),
                    ("Risk Awareness",           l2.risk_awareness),
                    ("User Appropriateness",     l2.user_appropriateness),
                ]
                for dname, ddim in dims:
                    score_color = C_GREEN if ddim.score >= 4 else (C_YELLOW if ddim.score >= 3 else C_RED)
                    print(f"    {dname:<25} {score_color}{ddim.score}/5{C_RESET}")
                    if ddim.sub_items:
                        for item_name, item in ddim.sub_items.items():
                            if item.met:
                                print(f"      {C_GREEN}✓{C_RESET} {C_DIM}{item_name}{C_RESET}")
                            else:
                                note = f": {C_DIM}{item.note}{C_RESET}" if item.note else ""
                                print(f"      {C_RED}✗{C_RESET} {item_name}{note}")
                    elif ddim.justification:
                        print(f"      {C_DIM}{ddim.justification[:70]}{C_RESET}")

    # ── Feedback Loop History ──
    if iteration_history and len(iteration_history) > 1:
        print(f"\n  {'-- Feedback Loop ':─<{W-2}}")
        # Find best iteration for marking
        prev_sc = None
        best_sc = 0
        best_it = 0
        for entry in iteration_history:
            if entry["score"] > best_sc:
                best_sc = entry["score"]
                best_it = entry["iteration"]
        # Display each iteration
        for entry in iteration_history:
            it = entry["iteration"]
            sc = entry["score"]
            fl = entry["failures"]
            passed = entry["passed"]
            status_color = C_GREEN if passed else C_RED
            status = "PASSED" if passed else "FAILED"
            # Show delta from previous iteration
            if prev_sc is not None:
                delta = sc - prev_sc
                delta_str = f"  {C_GREEN}↑{delta:+.2f}{C_RESET}" if delta > 0 else (
                    f"  {C_RED}↓{delta:+.2f}{C_RESET}" if delta < 0 else f"  {C_DIM}→ 0.00{C_RESET}"
                )
            else:
                delta_str = ""
            # Mark best iteration with ★
            pick = f"  {C_YELLOW}★ selected{C_RESET}" if it == best_it and len(iteration_history) > 1 else ""
            print(f"  Iteration {it}: {sc:.2f}/5.0 {status_color}{status}{C_RESET} — {fl} failures{delta_str}{pick}")
            prev_sc = sc
        total_iters = len(iteration_history)
        extra_calls = (total_iters - 1) * 2  # 2 LLM calls per re-run
        any_passed = any(e["passed"] for e in iteration_history)
        if any_passed:
            print(f"  {C_GREEN}Best: iteration {best_it}{C_RESET} ({best_sc:.2f}/5.0) — {extra_calls} extra LLM calls")
        else:
            print(f"  {C_YELLOW}Best: iteration {best_it}{C_RESET} ({best_sc:.2f}/5.0) — {extra_calls} extra LLM calls")

    print("\n" + "=" * W)


def main():
    parser = argparse.ArgumentParser(description="Stock Analysis Workflow (Swarm Architecture)")
    parser.add_argument("ticker", type=str, help="Stock ticker symbol (e.g., CRWD)")
    parser.add_argument(
        "--risk-tolerance",
        choices=["conservative", "moderate", "aggressive"],
        default="moderate",
        help="Risk tolerance level",
    )
    parser.add_argument(
        "--time-horizon",
        choices=["short", "medium", "long"],
        default="medium",
        help="Investment time horizon",
    )
    parser.add_argument(
        "--position-size-usd",
        type=float,
        default=10000,
        help="Dollar amount available to invest",
    )
    parser.add_argument(
        "--existing-holdings",
        type=str,
        default="",
        help="Comma-separated tickers already held",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Override LLM provider from config",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use cached/mock responses instead of calling LLM APIs",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation after analysis",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help="Max feedback iterations (1=no feedback loop, 3=up to 2 revision rounds)",
    )

    args = parser.parse_args()

    # Build risk profile
    holdings = [h.strip().upper() for h in args.existing_holdings.split(",") if h.strip()]
    risk_profile = RiskProfile(
        risk_tolerance=args.risk_tolerance,
        time_horizon=args.time_horizon,
        position_size_usd=args.position_size_usd,
        existing_holdings=holdings,
    )

    # Load config and create adapter
    config = load_config()
    provider = args.provider or config["workflow"]["provider"]

    if args.dry_run:
        adapter = _DryRunAdapter(model_name=f"{provider}-dry-run")
    else:
        adapter = create_adapter(provider, config)

    logger.info(f"Starting analysis for {args.ticker.upper()} using {adapter.get_model_name()}")
    logger.info(f"Risk profile: {risk_profile.model_dump()}")

    # Run pipeline (with or without feedback loop)
    eval_report = None
    iteration_history = None

    if args.skip_eval or args.max_iterations <= 1:
        # Original flow: run once, eval optionally
        result, pipeline_stats = run_pipeline(args.ticker.upper(), risk_profile, adapter, dry_run=args.dry_run)
        result_path = save_result(result)

        if not args.skip_eval:
            logger.info("Running evaluation...")
            try:
                from eval.run_eval import run_eval

                eval_report = run_eval(result, config)
                eval_path = result_path.with_suffix(".eval.json")
                with open(eval_path, "w") as f:
                    json.dump(eval_report.model_dump(), f, indent=2)
                logger.info(f"Eval report saved to {eval_path}")

                if eval_report.overall_passed:
                    logger.info("EVAL: PASSED")
                else:
                    logger.warning("EVAL: FAILED -- see eval report for details")
            except Exception as e:
                logger.warning(f"Eval skipped due to error: {e}")
    else:
        # Feedback loop: run pipeline → eval → revise → eval → ... up to N iterations
        logger.info(f"Feedback loop enabled: up to {args.max_iterations} iterations")
        try:
            result, pipeline_stats, eval_report, iteration_history = run_pipeline_with_feedback(
                args.ticker.upper(), risk_profile, adapter, config,
                max_iterations=args.max_iterations, dry_run=args.dry_run,
            )
            result_path = save_result(result)

            if eval_report:
                eval_path = result_path.with_suffix(".eval.json")
                with open(eval_path, "w") as f:
                    json.dump(eval_report.model_dump(), f, indent=2)
                logger.info(f"Eval report saved to {eval_path}")
        except Exception as e:
            logger.error(f"Feedback loop failed: {e}")
            import traceback
            traceback.print_exc()
            return

    # Print rich summary
    print_rich_summary(result, pipeline_stats, eval_report, iteration_history)


if __name__ == "__main__":
    main()
