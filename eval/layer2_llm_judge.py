"""Layer 2: LLM-as-Judge scoring — uses a different model to evaluate analysis quality.

Sub-item architecture: each dimension is broken into 4-6 boolean sub-items.
The LLM evaluates each sub-item as pass/fail. Dimension scores (1-5) are
computed deterministically from the sub-item pass rate.
"""

from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.base import LLMAdapter
from workflow.schema import (
    AggregatedDimensionScore,
    AnalysisResult,
    DeterministicEvalResult,
    DIMENSION_SUB_ITEMS,
    JudgeDimensionScore,
    LLMJudgePoolResult,
    LLMJudgeResult,
    SubItemResult,
    compute_dimension_score,
)

logger = logging.getLogger(__name__)

DIMENSION_WEIGHTS = {
    "causal_reasoning": 0.25,
    "information_completeness": 0.25,
    "actionability": 0.20,
    "risk_awareness": 0.20,
    "user_appropriateness": 0.10,
}
assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-6, (
    f"DIMENSION_WEIGHTS must sum to 1.0, got {sum(DIMENSION_WEIGHTS.values())}"
)

RUBRIC_PATH = Path(__file__).resolve().parent / "layer2_rubric.md"


def _build_sub_item_schema() -> dict:
    """Build the JSON schema for sub-item evaluation output.

    Generates a schema where each dimension contains named sub-items,
    each with {met: bool, note: string}.
    """
    sub_item_obj = {
        "type": "object",
        "properties": {
            "met": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "required": ["met", "note"],
    }

    schema = {
        "type": "object",
        "properties": {},
        "required": list(DIMENSION_SUB_ITEMS.keys()),
    }

    for dim_name, items in DIMENSION_SUB_ITEMS.items():
        dim_props = {}
        for item_name in items:
            dim_props[item_name] = {
                "type": "object",
                "properties": {
                    "met": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["met", "note"],
            }
        schema["properties"][dim_name] = {
            "type": "object",
            "properties": dim_props,
            "required": items.copy(),
        }

    return schema


def _normalize_sub_item_response(raw: dict) -> dict:
    """Normalize LLM sub-item response to handle common 8B model mistakes.

    Handles: missing items, string "true"/"false", bare booleans,
    non-dict dimension values, etc.
    """
    normalized = {}
    for dim_name, item_names in DIMENSION_SUB_ITEMS.items():
        dim_data = raw.get(dim_name, {})
        if not isinstance(dim_data, dict):
            dim_data = {}

        norm_dim = {}
        for item_name in item_names:
            item = dim_data.get(item_name, {})
            if not isinstance(item, dict):
                # Model might output just True/False instead of {met, note}
                if isinstance(item, bool):
                    item = {"met": item, "note": ""}
                else:
                    item = {"met": False, "note": "missing from response"}

            # Handle string "true"/"false" for met field
            met_val = item.get("met", False)
            if isinstance(met_val, str):
                met_val = met_val.lower().strip() in ("true", "yes", "1", "pass")

            norm_dim[item_name] = {
                "met": bool(met_val),
                "note": str(item.get("note", "")),
            }
        normalized[dim_name] = norm_dim

    return normalized


def _build_evidence_brief(result: AnalysisResult, l1_result: DeterministicEvalResult | None) -> str:
    """Build a structured evidence brief for the judge — replaces raw JSON dump.

    Organizes every detail from the analysis into clearly labeled sections,
    pre-computes percentages and cross-references so 8B judges can evaluate
    without doing arithmetic or parsing nested JSON.

    Like presenting a case in court: organized evidence, labeled exhibits.
    """
    decision = result.step5_decision
    data = result.step1_data
    fundamentals = result.step2_fundamental
    technicals = result.step3_technical
    catalysts_risks = result.step4_catalysts
    risk = result.risk_profile
    current_price = data.current_price

    lines: list[str] = []

    # ── Section 1: Verified Facts (pre-computed, no math needed) ─────────
    lines.append("## Verified Facts (pre-computed — use these for your evaluation)\n")

    entry = decision.entry_price.ideal
    ep_range = decision.entry_price.acceptable_range
    conservative = decision.target_price.conservative
    base_target = decision.target_price.base
    optimistic = decision.target_price.optimistic
    stop = decision.stop_loss

    if current_price > 0:
        lines.append(f"- Current price: ${current_price:.2f}")
        lines.append(f"- Entry: ${entry:.2f} (range ${ep_range[0]:.2f}–${ep_range[1]:.2f}) "
                     f"| {abs(entry - current_price) / current_price * 100:.1f}% from current")
        lines.append(f"- Conservative target: ${conservative:.2f} "
                     f"({(conservative - current_price) / current_price * 100:+.1f}% from current)")
        lines.append(f"- Base target: ${base_target:.2f} "
                     f"({(base_target - current_price) / current_price * 100:+.1f}% from current)")
        lines.append(f"- Optimistic target: ${optimistic:.2f} "
                     f"({(optimistic - current_price) / current_price * 100:+.1f}% from current)")
        lines.append(f"- Stop loss: ${stop:.2f} "
                     f"({(current_price - stop) / current_price * 100:.1f}% downside from current)")
        lines.append(f"- Risk/reward ratio: {decision.risk_reward_ratio:.1f}x")
    lines.append(f"- Recommendation: **{decision.recommendation.upper()}** "
                 f"at **{decision.confidence:.0%}** confidence")
    lines.append(f"- Position: ${decision.position_size_recommended_usd:,.0f} "
                 f"= {decision.position_size_pct_of_input:.0%} of "
                 f"${risk.position_size_usd:,.0f} budget")
    lines.append(f"- Time horizon: **{risk.time_horizon}** | "
                 f"Risk tolerance: **{risk.risk_tolerance}**")

    if risk.existing_holdings:
        lines.append(f"- Existing holdings: **{', '.join(risk.existing_holdings)}**")
    else:
        lines.append("- Existing holdings: **None**")

    if data.next_earnings_date:
        lines.append(f"- Next earnings date: **{data.next_earnings_date}**")
    else:
        lines.append("- Next earnings date: **NOT AVAILABLE** (yfinance returned null)")

    # ── Section 2: News ──────────────────────────────────────────────────
    lines.append("\n## Exhibit A: Recent News\n")
    for i, item in enumerate(data.recent_news, 1):
        lines.append(f"{i}. [{item.sentiment.upper()}] {item.headline} ({item.date})")

    # ── Section 3: Analyst Consensus ─────────────────────────────────────
    lines.append("\n## Exhibit B: Analyst Consensus\n")
    ac = data.analyst_consensus
    if ac:
        if ac.average_target_price:
            vs_current = ""
            if current_price > 0:
                delta_pct = (ac.average_target_price - current_price) / current_price * 100
                vs_current = f" ({delta_pct:+.1f}% vs current ${current_price:.2f})"
            lines.append(f"- Average target price: ${ac.average_target_price:.2f}{vs_current}")
        lines.append(f"- Ratings: {ac.buy_count} buy / {ac.hold_count} hold / {ac.sell_count} sell")
        total = ac.buy_count + ac.hold_count + ac.sell_count
        if total > 0:
            lines.append(f"- Consensus skew: {ac.buy_count/total:.0%} bullish")
        lines.append("")
        lines.append("→ **Question for judge**: Does the analysis *interpret* what this consensus "
                     "means, or just state the raw numbers?")
    else:
        lines.append("- No analyst consensus data available")

    # ── Section 4: Fundamental Analysis ──────────────────────────────────
    lines.append("\n## Exhibit C: Fundamental Analysis\n")
    lines.append(f"**Overall Rating: {fundamentals.overall_fundamental_rating}**\n")
    for dim_name, dim_label in [
        ("valuation", "Valuation"), ("growth", "Growth"),
        ("moat", "Competitive Moat"), ("balance_sheet", "Balance Sheet"),
    ]:
        dim = getattr(fundamentals, dim_name)
        lines.append(f"### {dim_label}")
        lines.append(f"Assessment: {dim.assessment}")
        lines.append("Evidence:")
        for ev in dim.evidence:
            lines.append(f"  - {ev}")
        lines.append("")

    lines.append("→ **Question for judge**: Do these assessments cite specific metrics "
                 "(P/E, growth %, FCF, etc.) or are they vague?")

    # ── Section 5: Technical Analysis ────────────────────────────────────
    lines.append("\n## Exhibit D: Technical Analysis\n")
    lines.append(f"**Overall Rating: {technicals.overall_technical_rating}** | "
                 f"Trend: {technicals.current_trend}")
    if technicals.rsi is not None:
        lines.append(f"- RSI: {technicals.rsi:.1f} ({technicals.rsi_signal})")
    else:
        lines.append("- RSI: N/A")
    lines.append(f"- MACD direction: {technicals.macd_direction or 'N/A'}")
    lines.append(f"- Support levels: {', '.join(f'${s:.2f}' for s in technicals.support_levels)}")
    lines.append(f"- Resistance levels: {', '.join(f'${r:.2f}' for r in technicals.resistance_levels)}")
    lines.append(f"- Volume: {technicals.volume_analysis}")

    # Cross-reference: stop loss vs supports
    nearest_support = min(technicals.support_levels, key=lambda s: abs(s - stop)) if technicals.support_levels else None
    if nearest_support:
        gap_pct = abs(stop - nearest_support) / stop * 100 if stop > 0 else 0
        if gap_pct < 3:
            lines.append(f"\n→ Stop loss ${stop:.2f} is near support ${nearest_support:.2f} "
                         f"({gap_pct:.1f}% gap) — **technically anchored**")
        else:
            lines.append(f"\n→ Stop loss ${stop:.2f} is {gap_pct:.1f}% away from nearest support "
                         f"${nearest_support:.2f} — **may lack technical basis**")

    # Cross-reference: targets vs resistances
    resistances_above = [r for r in technicals.resistance_levels if r > current_price]
    if resistances_above:
        base_target = decision.target_price.base
        nearest_resist = min(resistances_above, key=lambda r: abs(r - base_target))
        target_gap = abs(base_target - nearest_resist) / base_target * 100 if base_target > 0 else 0
        if target_gap < 5:
            lines.append(f"→ Base target ${base_target:.2f} is near resistance ${nearest_resist:.2f} "
                         f"({target_gap:.1f}% gap) — **technically anchored**")
        else:
            lines.append(f"→ Base target ${base_target:.2f} is {target_gap:.1f}% away from nearest "
                         f"resistance ${nearest_resist:.2f} — **may not be technically grounded**")

    # ── Section 6: Catalysts ─────────────────────────────────────────────
    lines.append("\n## Exhibit E: Catalysts\n")
    cat_categories = set()
    for i, c in enumerate(catalysts_risks.catalysts, 1):
        date_str = f" ({c.expected_date})" if c.expected_date and c.expected_date != "unknown" else ""
        lines.append(f"{i}. [{c.magnitude.upper()}] {c.event}{date_str}")
        # Track broad category for variety check
        cat_categories.add(_classify_catalyst_category(c.event))
    lines.append(f"\n→ Categories spanned: {len(cat_categories)} ({', '.join(cat_categories)})")

    # ── Section 7: Risks ─────────────────────────────────────────────────
    lines.append("\n## Exhibit F: Risks\n")
    risk_categories = set()
    for i, r in enumerate(catalysts_risks.risks, 1):
        date_str = f" ({r.expected_date})" if r.expected_date and r.expected_date != "unknown" else ""
        lines.append(f"{i}. [{r.magnitude.upper()}] {r.event}{date_str}")
        risk_categories.add(_classify_catalyst_category(r.event))
    lines.append(f"\n→ Categories spanned: {len(risk_categories)} ({', '.join(risk_categories)})")

    # ── Section 8: Portfolio / Concentration ──────────────────────────────
    lines.append("\n## Exhibit G: Portfolio Impact\n")
    lines.append(f"- Concentration risk flag: {'**YES**' if catalysts_risks.concentration_risk_flag else 'no'}")
    if catalysts_risks.correlation_with_holdings:
        lines.append(f"- Correlation analysis: {catalysts_risks.correlation_with_holdings}")
    else:
        lines.append("- Correlation analysis: **NOT PROVIDED**")
    if risk.existing_holdings:
        lines.append(f"- Holdings to cross-reference: {', '.join(risk.existing_holdings)}")
        lines.append("\n→ **Question for judge**: Does the analysis discuss how this position "
                     "correlates with or impacts these specific holdings?")
    else:
        lines.append("- No existing holdings — portfolio impact should mention general "
                     "diversification or allocation")

    # ── Section 9: Exit Strategy ─────────────────────────────────────────
    lines.append("\n## Exhibit H: Exit Strategy\n")
    if decision.exit_strategy:
        for tier in decision.exit_strategy:
            action = "STOP" if tier.action == "stop_loss" else "PROFIT"
            stop_move = f" → raise stop to ${tier.move_stop_to:.2f}" if tier.move_stop_to else ""
            lines.append(f"- ${tier.price:.2f} [{action}] sell {tier.sell_pct}%{stop_move} — {tier.note}")
    else:
        if decision.recommendation in ("buy", "hold"):
            lines.append("- **MISSING** — buy/hold recommendation has no exit strategy")
        else:
            lines.append("- None (sell/avoid — no exit strategy needed)")

    # ── Section 10: Narratives ───────────────────────────────────────────
    lines.append("\n## Exhibit I: Narrative Outputs\n")
    lines.append(f"### Key Conditions ({len(decision.key_conditions)} items)")
    for i, cond in enumerate(decision.key_conditions, 1):
        lines.append(f"{i}. {cond}")
    lines.append(f"\n### Bull Case ({len(decision.bull_case_summary.split('. '))} sentences)")
    lines.append(decision.bull_case_summary)
    lines.append(f"\n### Bear Case ({len(decision.bear_case_summary.split('. '))} sentences)")
    lines.append(decision.bear_case_summary)
    lines.append(f"\n### One-Line Summary")
    lines.append(decision.one_line_summary)

    # Cross-reference: does bear case quantify downside?
    has_dollar = "$" in decision.bear_case_summary
    has_pct = "%" in decision.bear_case_summary
    if has_dollar or has_pct:
        lines.append("\n→ Bear case contains quantified downside ✓")
    else:
        lines.append("\n→ Bear case has **no quantified downside** (no $ or % figures)")

    # ── Section 11: L1 Deterministic Results ─────────────────────────────
    if l1_result is not None:
        lines.append("\n## Exhibit J: Layer 1 Deterministic Check Results\n")
        failed = {name: check["reason"]
                  for name, check in l1_result.checks.items() if not check["passed"]}
        if failed:
            lines.append(f"**{len(failed)} of {l1_result.total_checks} checks FAILED.** "
                         "These are objective, code-verified issues:\n")
            for name, reason in failed.items():
                lines.append(f"- ❌ **{name}**: {reason}")
            lines.append("\n→ Factor these failures into your scoring for the relevant dimensions.")
        else:
            lines.append(f"✅ **ALL {l1_result.total_checks} checks PASSED** — "
                         "no objective issues found.")

    return "\n".join(lines)


def _classify_catalyst_category(event_text: str) -> str:
    """Rough classification of a catalyst/risk into a category for variety checking."""
    text = event_text.lower()
    if any(w in text for w in ("earning", "revenue", "profit", "eps", "guidance", "quarter")):
        return "earnings"
    if any(w in text for w in ("product", "launch", "release", "platform", "feature")):
        return "product"
    if any(w in text for w in ("regulat", "fda", "sec", "compliance", "legal", "litigation")):
        return "regulatory"
    if any(w in text for w in ("partner", "acquisition", "merger", "deal", "contract")):
        return "partnership/M&A"
    if any(w in text for w in ("compet", "rival", "market share")):
        return "competitive"
    if any(w in text for w in ("macro", "recession", "inflation", "rate", "fed", "tariff")):
        return "macro"
    if any(w in text for w in ("valuation", "multiple", "overvalued", "expensive")):
        return "valuation"
    if any(w in text for w in ("execution", "management", "operational")):
        return "execution"
    if any(w in text for w in ("technical", "momentum", "trend", "breakout")):
        return "technical"
    return "other"


def run_layer2(
    result: AnalysisResult,
    judge_adapter: LLMAdapter,
    l1_result: DeterministicEvalResult | None = None,
) -> LLMJudgeResult:
    """Run LLM-as-judge evaluation using a different model from the analysis model.

    The judge evaluates 25 boolean sub-items across 5 dimensions. Dimension
    scores (1-5) are computed deterministically from sub-item pass rates.

    Args:
        result: The analysis to evaluate.
        judge_adapter: LLM adapter for the judge model.
        l1_result: Optional Layer 1 results to provide as context to the judge.
    """

    rubric = RUBRIC_PATH.read_text()

    # Build structured evidence brief (replaces raw JSON dump)
    evidence_brief = _build_evidence_brief(result, l1_result)

    system_prompt = (
        "You are an expert financial analyst serving as a judge evaluating a stock analysis report. "
        "The evidence has been organized into labeled exhibits for your review. "
        "You must be rigorous and honest. For each sub-item, determine if it passes (true) or "
        "fails (false). Do not be generous — only mark 'met': true if the criterion is clearly "
        "satisfied. Pay close attention to the Verified Facts section and any Layer 1 check "
        "failures. The → arrows highlight cross-references and questions to consider. "
        "Respond ONLY with the JSON object described in the rubric."
    )

    user_prompt = (
        f"{evidence_brief}\n\n"
        f"## Evaluation Rubric\n\n{rubric}\n\n"
        f"Review all exhibits above and evaluate the analysis using the rubric. "
        f"Respond with the JSON format specified in the rubric."
    )

    schema = _build_sub_item_schema()
    raw_result = judge_adapter.complete_json(system_prompt, user_prompt, schema)

    # Normalize response to handle common small-model quirks
    normalized = _normalize_sub_item_response(raw_result)

    # Parse sub-items and compute scores deterministically
    dimension_scores = {}
    for dim_name, item_names in DIMENSION_SUB_ITEMS.items():
        dim_data = normalized[dim_name]
        sub_items = {}
        met_count = 0

        for item_name in item_names:
            item_data = dim_data[item_name]
            sub_item = SubItemResult(
                met=item_data["met"],
                note=item_data["note"],
            )
            sub_items[item_name] = sub_item
            if sub_item.met:
                met_count += 1

        score = compute_dimension_score(met_count, len(item_names))
        dimension_scores[dim_name] = JudgeDimensionScore(
            score=score,
            sub_items=sub_items,
        )

    # Compute weighted average from deterministic dimension scores
    weighted_avg = sum(
        dimension_scores[dim].score * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )
    weighted_avg = round(weighted_avg, 2)

    # Pass criteria: weighted avg >= 4.0 AND no dimension <= 2
    # (one weak dimension can't be masked by strong ones)
    dim_floor_ok = all(d.score > 2 for d in dimension_scores.values())
    passed = weighted_avg >= 4.0 and dim_floor_ok

    return LLMJudgeResult(
        causal_reasoning=dimension_scores["causal_reasoning"],
        information_completeness=dimension_scores["information_completeness"],
        actionability=dimension_scores["actionability"],
        risk_awareness=dimension_scores["risk_awareness"],
        user_appropriateness=dimension_scores["user_appropriateness"],
        overall_weighted_average=weighted_avg,
        passed=passed,
        judge_model=judge_adapter.get_model_name(),
    )


def run_layer2_pool(
    result: AnalysisResult,
    judge_adapters: list,
    max_workers: int = 4,
    l1_result: DeterministicEvalResult | None = None,
) -> LLMJudgePoolResult:
    """Run multiple LLM judges in parallel and aggregate results.

    Args:
        result: The analysis result to evaluate.
        judge_adapters: List of LLM adapters, one per judge model.
        max_workers: Max concurrent judge calls.
        l1_result: Optional Layer 1 results to provide as context to judges.

    Returns:
        LLMJudgePoolResult with individual + aggregated scores.

    Raises:
        RuntimeError: If all judges fail.
    """
    individual_results: list[LLMJudgeResult] = []
    failed_models: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for adapter in judge_adapters:
            future = pool.submit(run_layer2, result, adapter, l1_result)
            futures[future] = adapter.get_model_name()

        for future in as_completed(futures):
            model_name = futures[future]
            try:
                judge_result = future.result()
                individual_results.append(judge_result)
                logger.info(f"    Judge {model_name}: {judge_result.overall_weighted_average:.2f}/5.0")
            except Exception as e:
                logger.warning(f"    Judge {model_name} FAILED: {e}")
                failed_models.append(model_name)

    if not individual_results:
        raise RuntimeError(
            f"All {len(judge_adapters)} judges failed: {', '.join(failed_models)}"
        )

    # Aggregate dimension scores
    dimensions = {}
    for dim_name in DIMENSION_WEIGHTS:
        scores = [getattr(r, dim_name).score for r in individual_results]
        dimensions[dim_name] = AggregatedDimensionScore(
            mean_score=round(sum(scores) / len(scores), 2),
            min_score=min(scores),
            max_score=max(scores),
            scores=scores,
        )

    # Compute aggregated weighted average from mean dimension scores
    overall = sum(
        dimensions[dim].mean_score * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )
    overall = round(overall, 2)

    # Score spread: max - min of individual weighted averages
    individual_avgs = [r.overall_weighted_average for r in individual_results]
    spread = round(max(individual_avgs) - min(individual_avgs), 2)

    # Pool pass criteria:
    #   1. Weighted average >= 4.0
    #   2. At least half of judges individually passed
    #   3. No dimension mean <= 2.0
    judges_passed = sum(1 for r in individual_results if r.passed)
    majority_passed = judges_passed >= len(individual_results) / 2
    dim_floor_ok = all(dimensions[d].mean_score > 2.0 for d in DIMENSION_WEIGHTS)
    pool_passed = overall >= 4.0 and majority_passed and dim_floor_ok

    return LLMJudgePoolResult(
        individual_results=individual_results,
        judge_models=[r.judge_model for r in individual_results],
        num_judges=len(judge_adapters),
        num_succeeded=len(individual_results),
        causal_reasoning=dimensions["causal_reasoning"],
        information_completeness=dimensions["information_completeness"],
        actionability=dimensions["actionability"],
        risk_awareness=dimensions["risk_awareness"],
        user_appropriateness=dimensions["user_appropriateness"],
        overall_weighted_average=overall,
        passed=pool_passed,
        score_spread=spread,
    )
