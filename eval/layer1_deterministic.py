"""Layer 1: Deterministic checks — hard-coded, fast, 100% reproducible."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow.schema import AnalysisResult, DeterministicEvalResult


def run_layer1(result: AnalysisResult) -> DeterministicEvalResult:
    """Run all deterministic checks on the analysis result."""
    checks = {}
    decision = result.step5_decision
    data = result.step1_data
    risk = result.risk_profile

    # --- Format checks ---
    checks["required_fields_present"] = _check(
        all([
            decision.ticker,
            decision.recommendation,
            decision.entry_price,
            decision.target_price,
            decision.stop_loss > 0,
            decision.key_conditions,
            decision.bull_case_summary,
            decision.bear_case_summary,
            decision.one_line_summary,
        ]),
        "All required fields must be present and non-empty",
    )

    checks["recommendation_valid"] = _check(
        decision.recommendation in ("buy", "hold", "sell", "avoid"),
        f"Recommendation '{decision.recommendation}' must be buy/hold/sell/avoid",
    )

    # --- Math consistency checks ---
    expected_pct = decision.position_size_recommended_usd / risk.position_size_usd
    checks["position_size_pct_math"] = _check(
        abs(decision.position_size_pct_of_input - expected_pct) <= 0.02,
        f"position_size_pct ({decision.position_size_pct_of_input:.2f}) should ≈ "
        f"recommended / input = {expected_pct:.2f}",
    )

    # Price ordering and R:R only meaningful for buy/hold
    if decision.recommendation in ("buy", "hold"):
        # Replicate the same guards as _assemble_decision
        entry = decision.entry_price.ideal
        stop = decision.stop_loss
        denominator = entry - stop
        if denominator <= 0:
            denominator = entry * 0.1  # mirrors stop = entry * 0.9
        numerator = decision.target_price.base - entry
        if numerator <= 0:
            numerator = denominator * 0.5  # mirrors the 0.5:1 floor
        expected_rr = max(0.01, round(numerator / denominator, 2))

        checks["risk_reward_math"] = _check(
            abs(decision.risk_reward_ratio - expected_rr) <= 0.3,
            f"risk_reward_ratio ({decision.risk_reward_ratio:.2f}) should ≈ "
            f"expected {expected_rr:.2f} (tolerance ±0.3)",
        )

        checks["price_ordering"] = _check(
            decision.stop_loss < decision.entry_price.ideal
            < decision.target_price.conservative
            < decision.target_price.base
            < decision.target_price.optimistic,
            f"Must have stop ({decision.stop_loss}) < entry ({decision.entry_price.ideal}) "
            f"< conservative ({decision.target_price.conservative}) "
            f"< base ({decision.target_price.base}) "
            f"< optimistic ({decision.target_price.optimistic})",
        )

        # Entry price range consistency
        ep_range = decision.entry_price.acceptable_range
        checks["entry_range_valid"] = _check(
            len(ep_range) == 2 and ep_range[0] <= decision.entry_price.ideal <= ep_range[1],
            f"Entry ideal ({decision.entry_price.ideal}) must be within "
            f"acceptable_range [{ep_range[0]}, {ep_range[1]}]",
        )

    # --- Bound checks ---
    checks["confidence_bounds"] = _check(
        0 <= decision.confidence <= 1,
        f"Confidence ({decision.confidence}) must be between 0 and 1",
    )

    checks["stop_loss_below_entry"] = _check(
        0 < decision.stop_loss < decision.entry_price.ideal,
        f"Stop loss ({decision.stop_loss}) must be > 0 and < entry price ({decision.entry_price.ideal})",
    )

    if data.current_price > 0:
        max_target = data.current_price * 3.0
        checks["target_within_200pct"] = _check(
            decision.target_price.optimistic <= max_target,
            f"Optimistic target ({decision.target_price.optimistic}) must be within "
            f"200% of current price ({data.current_price}), max = {max_target:.2f}",
        )

        entry_deviation = abs(decision.entry_price.ideal - data.current_price) / data.current_price
        checks["entry_near_current_price"] = _check(
            entry_deviation <= 0.15,
            f"Entry price ({decision.entry_price.ideal}) must be within 15% of "
            f"current price ({data.current_price}), deviation = {entry_deviation:.1%}",
        )

    checks["position_size_within_budget"] = _check(
        decision.position_size_recommended_usd <= risk.position_size_usd,
        f"Recommended position (${decision.position_size_recommended_usd:,.0f}) must be ≤ "
        f"available (${risk.position_size_usd:,.0f})",
    )

    # --- Data freshness checks ---
    checks["has_recent_news"] = _check(
        len(data.recent_news) >= 1,
        "Must include at least 1 recent news item",
    )

    # --- Risk profile alignment ---
    if risk.risk_tolerance == "conservative":
        checks["conservative_position_size"] = _check(
            decision.position_size_pct_of_input <= 0.55,  # 0.5 + small tolerance
            f"Conservative investor: position_size_pct ({decision.position_size_pct_of_input:.2f}) should be ≤ 0.5",
        )

        downside_pct = (decision.entry_price.ideal - decision.stop_loss) / decision.entry_price.ideal
        checks["conservative_stop_loss"] = _check(
            downside_pct <= 0.11,  # 10% + small tolerance
            f"Conservative investor: stop loss should be within 10% of entry. "
            f"Actual downside: {downside_pct:.1%}",
        )

    if risk.risk_tolerance == "aggressive":
        checks["aggressive_has_stop_loss"] = _check(
            decision.stop_loss > 0,
            "Even aggressive investors must have a stop loss",
        )

    # --- Correlation/concentration check ---
    # Use the pipeline's own concentration_risk_flag (computed from yfinance sectors)
    # rather than reimplementing with a hardcoded tech-ticker set.
    if result.step4_catalysts.concentration_risk_flag:
        has_concentration_mention = (
            result.step4_catalysts.correlation_with_holdings
            and len(result.step4_catalysts.correlation_with_holdings) > 5
        )
        checks["concentration_risk_mentioned"] = _check(
            has_concentration_mention,
            "Pipeline flagged sector concentration risk — "
            "must include correlation_with_holdings explanation",
        )

    # --- Exit strategy validity (#7) ---
    if decision.recommendation in ("buy", "hold"):
        es = decision.exit_strategy
        checks["exit_strategy_present"] = _check(
            len(es) >= 2,
            f"Buy/hold must have exit strategy with ≥ 2 tiers, got {len(es)}",
        )
        if len(es) >= 2:
            # First tier must be stop_loss
            checks["exit_strategy_stop_first"] = _check(
                es[0].action == "stop_loss",
                f"First exit tier must be stop_loss, got '{es[0].action}'",
            )
            # Prices should be ascending
            prices = [t.price for t in es]
            ascending = all(prices[i] < prices[i + 1] for i in range(len(prices) - 1))
            checks["exit_strategy_ascending"] = _check(
                ascending,
                f"Exit tier prices must be ascending: {prices}",
            )
            # Last take_profit tier should sell 100% (close position)
            profit_tiers = [t for t in es if t.action == "take_profit"]
            if profit_tiers:
                checks["exit_strategy_closes"] = _check(
                    profit_tiers[-1].sell_pct == 100,
                    f"Last take_profit tier must sell 100%, got {profit_tiers[-1].sell_pct}%",
                )
    elif decision.recommendation in ("sell", "avoid"):
        checks["exit_strategy_empty_for_sell"] = _check(
            len(decision.exit_strategy) == 0,
            f"Sell/avoid should have no exit strategy, got {len(decision.exit_strategy)} tiers",
        )

    # --- Time horizon matches profile (#8) ---
    checks["time_horizon_matches"] = _check(
        decision.time_horizon == risk.time_horizon,
        f"Decision time_horizon '{decision.time_horizon}' must match "
        f"profile '{risk.time_horizon}'",
    )

    # --- Sell/avoid position size (#17) ---
    if decision.recommendation in ("sell", "avoid"):
        checks["sell_avoid_small_position"] = _check(
            decision.position_size_pct_of_input <= 0.10,
            f"Sell/avoid: position_size_pct ({decision.position_size_pct_of_input:.2f}) "
            f"should be ≤ 0.10 (10%)",
        )

    # --- Minimum catalysts and risks (#34) ---
    checks["min_catalysts"] = _check(
        len(result.step4_catalysts.catalysts) >= 2,
        f"Must have ≥ 2 catalysts, got {len(result.step4_catalysts.catalysts)}",
    )
    checks["min_risks"] = _check(
        len(result.step4_catalysts.risks) >= 2,
        f"Must have ≥ 2 risks, got {len(result.step4_catalysts.risks)}",
    )

    # --- Minimum key conditions (#37) ---
    checks["min_key_conditions"] = _check(
        len(decision.key_conditions) >= 2,
        f"Must have ≥ 2 key_conditions, got {len(decision.key_conditions)}",
    )

    # Summarize
    passed_count = sum(1 for c in checks.values() if c["passed"])
    all_passed = all(c["passed"] for c in checks.values())

    return DeterministicEvalResult(
        passed=all_passed,
        checks=checks,
        total_checks=len(checks),
        passed_checks=passed_count,
    )


def _check(condition: bool, reason: str) -> dict:
    return {"passed": condition, "reason": reason if not condition else "OK"}
