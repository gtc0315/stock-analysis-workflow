#!/usr/bin/env python3
"""Run same analysis across models, compare eval scores."""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eval.run_eval import run_eval
from workflow.runner import create_adapter, run_pipeline, save_result
from workflow.schema import RiskProfile

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = PROJECT_ROOT / "results"


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def run_comparison(
    ticker: str,
    risk_profile: RiskProfile,
    providers: list[str],
    config: dict,
) -> list[dict]:
    """Run analysis across multiple providers and collect results."""
    results = []

    for provider in providers:
        logger.info(f"\n{'='*60}")
        logger.info(f"Running analysis with provider: {provider}")
        logger.info(f"{'='*60}")

        try:
            adapter = create_adapter(provider, config)
            start_time = time.time()

            analysis, _stats = run_pipeline(ticker, risk_profile, adapter)
            elapsed = time.time() - start_time

            # Save result
            result_path = save_result(analysis)

            # Run eval
            eval_report = run_eval(analysis, config)
            eval_path = result_path.with_suffix(".eval.json")
            with open(eval_path, "w") as f:
                json.dump(eval_report.model_dump(), f, indent=2)

            # Collect usage stats
            total_tokens_in = 0
            total_tokens_out = 0
            # Estimate from adapter's last usage (rough — real implementation would track all calls)
            total_tokens = adapter.last_usage.get("input_tokens", 0) + adapter.last_usage.get("output_tokens", 0)

            results.append({
                "provider": provider,
                "model": adapter.get_model_name(),
                "analysis": analysis,
                "eval": eval_report,
                "latency_s": round(elapsed, 1),
                "tokens_total": total_tokens,
                "cost": _estimate_total_cost(adapter.get_model_name(), total_tokens),
                "result_path": str(result_path),
            })

        except Exception as e:
            logger.error(f"Provider {provider} failed: {e}")
            results.append({
                "provider": provider,
                "model": "N/A",
                "error": str(e),
            })

    return results


def _estimate_total_cost(model: str, tokens: int) -> float:
    """Rough cost estimate."""
    rates = {
        "claude-sonnet-4-5-20250929": 0.009,  # ~$9/MTok average
        "gpt-4o": 0.00625,  # ~$6.25/MTok average
        "llama3": 0,
    }
    rate = rates.get(model, 0.005)
    return round(tokens * rate / 1000, 4)


def print_comparison_table(ticker: str, risk_profile: RiskProfile, results: list[dict]):
    """Print a formatted comparison table."""

    print(f"\nTicker: {ticker} | Risk: {risk_profile.risk_tolerance} | "
          f"Horizon: {risk_profile.time_horizon} | Amount: ${risk_profile.position_size_usd:,.0f}")
    print()

    # Collect column data
    columns = []
    for r in results:
        if "error" in r:
            columns.append({
                "header": f"{r['provider']} (FAILED)",
                "recommendation": "ERROR",
                "entry_price": "N/A",
                "target_base": "N/A",
                "stop_loss": "N/A",
                "confidence": "N/A",
                "risk_reward": "N/A",
                "eval_l1": "ERROR",
                "eval_l2": "N/A",
                "l2_causal": "N/A",
                "l2_completeness": "N/A",
                "l2_actionability": "N/A",
                "l2_risk": "N/A",
                "l2_appropriateness": "N/A",
                "tokens": "N/A",
                "cost": "N/A",
                "latency": "N/A",
            })
        else:
            d = r["analysis"].step5_decision
            ev = r["eval"]
            l2 = ev.layer2
            l2_pool = getattr(ev, "layer2_pool", None)

            # Prefer pool scores when available
            if l2_pool:
                l2_score = f"{l2_pool.overall_weighted_average:.1f}"
                l2_causal = f"{l2_pool.causal_reasoning.mean_score:.1f}"
                l2_completeness = f"{l2_pool.information_completeness.mean_score:.1f}"
                l2_actionability = f"{l2_pool.actionability.mean_score:.1f}"
                l2_risk = f"{l2_pool.risk_awareness.mean_score:.1f}"
                l2_appropriateness = f"{l2_pool.user_appropriateness.mean_score:.1f}"
            elif l2:
                l2_score = f"{l2.overall_weighted_average:.1f}"
                l2_causal = str(l2.causal_reasoning.score)
                l2_completeness = str(l2.information_completeness.score)
                l2_actionability = str(l2.actionability.score)
                l2_risk = str(l2.risk_awareness.score)
                l2_appropriateness = str(l2.user_appropriateness.score)
            else:
                l2_score = "N/A"
                l2_causal = l2_completeness = l2_actionability = l2_risk = l2_appropriateness = "N/A"

            columns.append({
                "header": r["model"],
                "recommendation": d.recommendation,
                "entry_price": f"${d.entry_price.ideal:.0f}",
                "target_base": f"${d.target_price.base:.0f}",
                "stop_loss": f"${d.stop_loss:.0f}",
                "confidence": f"{d.confidence:.2f}",
                "risk_reward": f"{d.risk_reward_ratio:.2f}",
                "eval_l1": "PASS" if ev.layer1.passed else f"FAIL ({ev.layer1.passed_checks}/{ev.layer1.total_checks})",
                "eval_l2": l2_score,
                "l2_causal": l2_causal,
                "l2_completeness": l2_completeness,
                "l2_actionability": l2_actionability,
                "l2_risk": l2_risk,
                "l2_appropriateness": l2_appropriateness,
                "tokens": f"{r['tokens_total']:,}" if r.get("tokens_total") else "N/A",
                "cost": f"${r['cost']:.2f}" if r.get("cost") is not None else "N/A",
                "latency": f"{r['latency_s']}s" if r.get("latency_s") else "N/A",
            })

    # Format table
    label_width = 22
    col_width = 16

    # Header
    header_line = " " * label_width + "| " + " | ".join(c["header"][:col_width-2].ljust(col_width - 2) for c in columns)
    separator = "-" * label_width + "|" + "|".join("-" * col_width for _ in columns)

    print(header_line)
    print(separator)

    rows = [
        ("Recommendation", "recommendation"),
        ("Entry Price", "entry_price"),
        ("Target (base)", "target_base"),
        ("Stop Loss", "stop_loss"),
        ("Confidence", "confidence"),
        ("Risk/Reward", "risk_reward"),
    ]
    for label, key in rows:
        values = " | ".join(c[key].ljust(col_width - 2) for c in columns)
        print(f"{label:<{label_width}}| {values}")

    print(separator)

    eval_rows = [
        ("Eval L1 (determ.)", "eval_l1"),
        ("Eval L2 (judge avg)", "eval_l2"),
        ("  - Causal", "l2_causal"),
        ("  - Completeness", "l2_completeness"),
        ("  - Actionability", "l2_actionability"),
        ("  - Risk Awareness", "l2_risk"),
        ("  - Appropriateness", "l2_appropriateness"),
    ]
    for label, key in eval_rows:
        values = " | ".join(c[key].ljust(col_width - 2) for c in columns)
        print(f"{label:<{label_width}}| {values}")

    print(separator)

    meta_rows = [
        ("Tokens Used", "tokens"),
        ("Cost", "cost"),
        ("Latency", "latency"),
    ]
    for label, key in meta_rows:
        values = " | ".join(c[key].ljust(col_width - 2) for c in columns)
        print(f"{label:<{label_width}}| {values}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Cross-Model Stock Analysis Comparison")
    parser.add_argument("ticker", type=str, help="Stock ticker symbol")
    parser.add_argument(
        "--risk-tolerance",
        choices=["conservative", "moderate", "aggressive"],
        default="moderate",
    )
    parser.add_argument(
        "--time-horizon",
        choices=["short", "medium", "long"],
        default="medium",
    )
    parser.add_argument("--position-size-usd", type=float, default=10000)
    parser.add_argument("--existing-holdings", type=str, default="")
    parser.add_argument(
        "--providers",
        type=str,
        default=None,
        help="Comma-separated list of providers to compare (default: all configured)",
    )

    args = parser.parse_args()

    holdings = [h.strip().upper() for h in args.existing_holdings.split(",") if h.strip()]
    risk_profile = RiskProfile(
        risk_tolerance=args.risk_tolerance,
        time_horizon=args.time_horizon,
        position_size_usd=args.position_size_usd,
        existing_holdings=holdings,
    )

    config = load_config()

    if args.providers:
        providers = [p.strip() for p in args.providers.split(",")]
    else:
        # Use all configured providers
        providers = list(config.get("providers", {}).keys())

    logger.info(f"Comparing models for {args.ticker.upper()}: {', '.join(providers)}")

    results = run_comparison(args.ticker.upper(), risk_profile, providers, config)
    print_comparison_table(args.ticker.upper(), risk_profile, results)

    # Save comparison results
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    comparison_path = RESULTS_DIR / f"comparison_{args.ticker.upper()}_{timestamp}.json"
    summary = []
    for r in results:
        if "error" in r:
            summary.append({"provider": r["provider"], "error": r["error"]})
        else:
            ev = r["eval"]
            l2_pool = getattr(ev, "layer2_pool", None)
            summary.append({
                "provider": r["provider"],
                "model": r["model"],
                "recommendation": r["analysis"].step5_decision.recommendation,
                "confidence": r["analysis"].step5_decision.confidence,
                "eval_l1_passed": ev.layer1.passed,
                "eval_l2_score": (
                    l2_pool.overall_weighted_average if l2_pool
                    else (ev.layer2.overall_weighted_average if ev.layer2 else None)
                ),
                "eval_l2_judges": (
                    l2_pool.num_succeeded if l2_pool
                    else (1 if ev.layer2 else 0)
                ),
                "latency_s": r["latency_s"],
                "cost": r["cost"],
                "result_path": r["result_path"],
            })
    with open(comparison_path, "w") as f:
        json.dump({"ticker": args.ticker.upper(), "risk_profile": risk_profile.model_dump(), "results": summary}, f, indent=2)
    logger.info(f"Comparison saved to {comparison_path}")


if __name__ == "__main__":
    main()
