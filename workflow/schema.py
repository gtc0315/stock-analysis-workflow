from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# --- User Input ---

class RiskProfile(BaseModel):
    """User's risk profile for the analysis."""
    risk_tolerance: str = Field(description="conservative | moderate | aggressive")
    time_horizon: str = Field(description="short | medium | long")
    position_size_usd: float = Field(gt=0, description="Dollar amount available to invest")
    existing_holdings: list[str] = Field(default_factory=list, description="Tickers already held")

    @field_validator("risk_tolerance")
    @classmethod
    def validate_risk(cls, v: str) -> str:
        if v not in ("conservative", "moderate", "aggressive"):
            raise ValueError("risk_tolerance must be conservative, moderate, or aggressive")
        return v

    @field_validator("time_horizon")
    @classmethod
    def validate_horizon(cls, v: str) -> str:
        if v not in ("short", "medium", "long"):
            raise ValueError("time_horizon must be short, medium, or long")
        return v


# --- Step 1: Data Gathering ---

class NewsItem(BaseModel):
    headline: str = Field(description="News headline text")
    date: str = Field(description="Date of the news item (YYYY-MM-DD or relative)")
    sentiment: str = Field(description="positive | negative | neutral")

class AnalystConsensus(BaseModel):
    average_target_price: Optional[float] = Field(default=None, description="Average analyst target price")
    buy_count: int = Field(default=0, ge=0, description="Number of buy ratings")
    hold_count: int = Field(default=0, ge=0, description="Number of hold ratings")
    sell_count: int = Field(default=0, ge=0, description="Number of sell ratings")

class DataGatheringOutput(BaseModel):
    """Step 1 output: raw data about the stock."""
    ticker: str
    current_price: float = Field(gt=0)
    price_date: str = Field(description="Date/time of the price data")
    pe_ratio: Optional[float] = Field(default=None, description="Price-to-earnings ratio")
    forward_pe: Optional[float] = Field(default=None, description="Forward price-to-earnings ratio")
    ps_ratio: Optional[float] = Field(default=None, description="Price-to-sales ratio")
    market_cap_billions: float = Field(gt=0, description="Market cap in billions USD")
    week_52_high: float = Field(gt=0)
    week_52_low: float = Field(gt=0)
    beta: Optional[float] = Field(default=None, description="Stock beta")
    short_interest_pct: Optional[float] = Field(default=None, ge=0, description="Short interest %")
    recent_news: list[NewsItem] = Field(min_length=1, description="Recent news items")
    next_earnings_date: Optional[str] = Field(default=None, description="Next earnings date")
    analyst_consensus: Optional[AnalystConsensus] = None
    data_retrieval_timestamp: str = Field(description="ISO timestamp of data retrieval")


# --- Step 2: Fundamental Analysis ---

class FundamentalDimension(BaseModel):
    assessment: str = Field(description="Summary assessment")
    evidence: list[str] = Field(min_length=1, description="Supporting evidence points")

class FundamentalAnalysisOutput(BaseModel):
    """Step 2 output: fundamental analysis."""
    ticker: str
    valuation: FundamentalDimension = Field(description="Cheap/fair/expensive assessment")
    growth: FundamentalDimension = Field(description="Revenue/earnings growth trajectory")
    moat: FundamentalDimension = Field(description="Competitive moat assessment")
    balance_sheet: FundamentalDimension = Field(description="Balance sheet health")
    overall_fundamental_rating: str = Field(description="strong | moderate | weak")


# --- Step 3: Technical Analysis ---

class TechnicalAnalysisOutput(BaseModel):
    """Step 3 output: technical analysis."""
    ticker: str
    current_trend: str = Field(description="uptrend | downtrend | consolidation")
    support_levels: list[float] = Field(min_length=1, description="Key support price levels")
    resistance_levels: list[float] = Field(min_length=1, description="Key resistance price levels")
    rsi: Optional[float] = Field(default=None, ge=0, le=100, description="RSI value")
    rsi_signal: Optional[str] = Field(default=None, description="oversold | neutral | overbought")
    macd_direction: Optional[str] = Field(default=None, description="bullish | bearish | neutral")
    volume_analysis: str = Field(description="Volume assessment")
    overall_technical_rating: str = Field(description="bullish | neutral | bearish")


# --- Step 4: Catalyst & Risk ---

class Catalyst(BaseModel):
    event: str = Field(description="Description of the catalyst")
    expected_date: Optional[str] = Field(default=None, description="When it might happen")
    impact: str = Field(description="positive | negative")
    magnitude: str = Field(description="high | medium | low")

class CatalystRiskOutput(BaseModel):
    """Step 4 output: catalysts and risks."""
    ticker: str
    catalysts: list[Catalyst] = Field(min_length=1, description="Upcoming catalysts")
    risks: list[Catalyst] = Field(min_length=1, description="Key risks")
    correlation_with_holdings: Optional[str] = Field(
        default=None,
        description="Assessment of correlation with user's existing holdings",
    )
    concentration_risk_flag: bool = Field(
        default=False,
        description="True if adding this stock increases sector concentration",
    )


# --- Worker Schemas (Swarm Architecture) ---

class NewsWorkerOutput(BaseModel):
    """Worker 1a output: recent news headlines."""
    headlines: list[NewsItem] = Field(min_length=1, description="3-5 recent news headlines")

class AnalystWorkerOutput(BaseModel):
    """Worker 1b output: analyst consensus estimate."""
    average_target_price: Optional[float] = Field(default=None, description="Average analyst target price")
    buy_count: int = Field(default=0, ge=0, description="Number of buy ratings")
    hold_count: int = Field(default=0, ge=0, description="Number of hold ratings")
    sell_count: int = Field(default=0, ge=0, description="Number of sell ratings")

class DimensionWorkerOutput(BaseModel):
    """Workers 2a-2d output: single analysis dimension."""
    assessment: str = Field(min_length=3, description="1-2 sentence summary")
    evidence: list[str] = Field(min_length=1, description="Supporting evidence as plain text strings")

class TechInterpretationOutput(BaseModel):
    """Worker 3a output: technical interpretation of pre-computed indicators."""
    current_trend: str = Field(description="uptrend | downtrend | consolidation")
    overall_technical_rating: str = Field(description="bullish | neutral | bearish")
    volume_analysis: str = Field(min_length=5, description="1-2 sentence volume interpretation")

class CatalystWorkerOutput(BaseModel):
    """Worker 3b output: upcoming positive catalysts."""
    catalysts: list[Catalyst] = Field(min_length=1, description="3+ upcoming catalysts")

class RiskWorkerOutput(BaseModel):
    """Worker 3c output: key risks."""
    risks: list[Catalyst] = Field(min_length=1, description="3+ key risks")


# --- Step 5: Decision Synthesis (broken into sub-steps) ---

class PriceTarget(BaseModel):
    conservative: float = Field(gt=0)
    base: float = Field(gt=0)
    optimistic: float = Field(gt=0)

class EntryPrice(BaseModel):
    ideal: float = Field(gt=0)
    acceptable_range: list[float] = Field(min_length=2, max_length=2, description="[low, high]")


# Step 5a: LLM picks recommendation + price levels + position size
class RecommendationOutput(BaseModel):
    """Step 5a output: recommendation, price levels, and position sizing."""
    ticker: str
    recommendation: str = Field(description="buy | hold | sell | avoid")
    confidence: float = Field(ge=0, le=1)
    entry_price: EntryPrice
    target_price: PriceTarget
    stop_loss: float = Field(gt=0)
    position_size_recommended_usd: float = Field(ge=0)

    @field_validator("recommendation")
    @classmethod
    def validate_recommendation(cls, v: str) -> str:
        if v not in ("buy", "hold", "sell", "avoid"):
            raise ValueError("recommendation must be buy, hold, sell, or avoid")
        return v


# Step 5b: LLM writes narrative fields (no math)
class NarrativeOutput(BaseModel):
    """Step 5b output: conditions, summaries, and narratives."""
    key_conditions: list[str] = Field(min_length=1)
    bull_case_summary: str = Field(min_length=10)
    bear_case_summary: str = Field(min_length=10)
    one_line_summary: str = Field(min_length=10)


# Exit strategy tier (computed deterministically from targets + risk tolerance)
class ExitTier(BaseModel):
    """Single tier in a position exit strategy."""
    price: float = Field(gt=0)
    action: str = Field(description="stop_loss | take_profit")
    sell_pct: int = Field(ge=1, le=100, description="% of remaining position to sell")
    move_stop_to: Optional[float] = Field(default=None, description="Raise stop to this price after executing")
    note: str = Field(description="Brief explanation of this tier")


# Final assembled output (Step 5c computes derived fields in code)
class DecisionOutput(BaseModel):
    """Step 5 output: final investment recommendation."""
    ticker: str
    recommendation: str = Field(description="buy | hold | sell | avoid")
    confidence: float = Field(ge=0, le=1)
    entry_price: EntryPrice
    target_price: PriceTarget
    stop_loss: float = Field(gt=0)
    position_size_recommended_usd: float = Field(ge=0)
    position_size_pct_of_input: float = Field(ge=0, le=1)
    time_horizon: str
    risk_reward_ratio: float = Field(gt=0)
    exit_strategy: list[ExitTier] = Field(default_factory=list, description="Tiered exit plan based on time horizon")
    key_conditions: list[str] = Field(min_length=1)
    bull_case_summary: str = Field(min_length=10)
    bear_case_summary: str = Field(min_length=10)
    one_line_summary: str = Field(min_length=10)

    @field_validator("recommendation")
    @classmethod
    def validate_recommendation(cls, v: str) -> str:
        if v not in ("buy", "hold", "sell", "avoid"):
            raise ValueError("recommendation must be buy, hold, sell, or avoid")
        return v


# --- Full Analysis Result ---

class AnalysisResult(BaseModel):
    """Complete analysis result across all steps."""
    ticker: str
    risk_profile: RiskProfile
    model_name: str
    timestamp: str
    step1_data: DataGatheringOutput
    step2_fundamental: FundamentalAnalysisOutput
    step3_technical: TechnicalAnalysisOutput
    step4_catalysts: CatalystRiskOutput
    step5_decision: DecisionOutput


# --- Eval Schemas ---

class DeterministicEvalResult(BaseModel):
    """Layer 1 eval output."""
    passed: bool
    checks: dict[str, dict] = Field(description="Check name -> {passed, reason}")
    total_checks: int
    passed_checks: int

class SubItemResult(BaseModel):
    """Single boolean sub-item evaluation result."""
    met: bool = Field(description="Whether this check passed")
    note: str = Field(default="", description="Brief justification (1 sentence)")


# Single source of truth: sub-item names per dimension.
DIMENSION_SUB_ITEMS: dict[str, list[str]] = {
    "causal_reasoning": [
        "metrics_cited",
        "technical_alignment",
        "recommendation_follows_evidence",
        "confidence_calibrated",
        "counterarguments_present",
    ],
    "information_completeness": [
        "news_substantive",
        "earnings_discussed",
        "analyst_consensus_interpreted",
        "catalyst_variety",
        "risk_variety",
        "bull_bear_balanced",
    ],
    "actionability": [
        "entry_range_justified",
        "targets_tiered_and_realistic",
        "stop_loss_technical_basis",
        "conditions_measurable",
        "summary_standalone",
    ],
    "risk_awareness": [
        "diverse_risk_categories",
        "bear_case_detailed",
        "stop_loss_explained",
        "portfolio_impact_discussed",
        "downside_scenario_quantified",
    ],
    "user_appropriateness": [
        "position_size_appropriate",
        "time_horizon_matched",
        "holdings_correlation_noted",
        "tone_matches_profile",
    ],
}


def compute_dimension_score(met_count: int, total_count: int) -> int:
    """Compute 1-5 dimension score from sub-item pass rate.

    Formula: max(1, round(1 + 4 * (met_count / total_count)))
    Maps: 0% → 1, ~50% → 3, 100% → 5
    """
    if total_count == 0:
        return 1
    return max(1, round(1 + 4 * (met_count / total_count)))


class JudgeDimensionScore(BaseModel):
    score: int = Field(ge=1, le=5)
    justification: Optional[str] = Field(default=None)
    sub_items: Optional[dict[str, SubItemResult]] = Field(
        default=None,
        description="Per-sub-item pass/fail results (None for old-format evals)",
    )

class LLMJudgeResult(BaseModel):
    """Layer 2 eval output."""
    causal_reasoning: JudgeDimensionScore
    information_completeness: JudgeDimensionScore
    actionability: JudgeDimensionScore
    risk_awareness: JudgeDimensionScore
    user_appropriateness: JudgeDimensionScore
    overall_weighted_average: float
    passed: bool = Field(description="True if overall >= 4.0 and no dimension <= 2")
    judge_model: str

class AggregatedDimensionScore(BaseModel):
    """Aggregated score across multiple judges for one dimension."""
    mean_score: float = Field(ge=1.0, le=5.0)
    min_score: int = Field(ge=1, le=5)
    max_score: int = Field(ge=1, le=5)
    scores: list[int] = Field(description="Individual judge scores")

class LLMJudgePoolResult(BaseModel):
    """Layer 2 eval output from a pool of LLM judges."""
    individual_results: list[LLMJudgeResult]
    judge_models: list[str]
    num_judges: int
    num_succeeded: int
    causal_reasoning: AggregatedDimensionScore
    information_completeness: AggregatedDimensionScore
    actionability: AggregatedDimensionScore
    risk_awareness: AggregatedDimensionScore
    user_appropriateness: AggregatedDimensionScore
    overall_weighted_average: float
    passed: bool = Field(description="True if overall >= 4.0, majority of judges pass, no dimension mean <= 2")
    score_spread: float = Field(description="Max - min of individual weighted averages")

class EvalReport(BaseModel):
    """Combined eval report."""
    ticker: str
    model_name: str
    timestamp: str
    layer1: DeterministicEvalResult
    layer2: Optional[LLMJudgeResult] = None
    layer2_pool: Optional[LLMJudgePoolResult] = None
    overall_passed: bool


def get_schema_dict(model_class: type[BaseModel]) -> dict:
    """Get a simplified JSON schema dict for prompting.

    Resolves $defs/$ref into a flat structure so smaller models can understand it.
    """
    full_schema = model_class.model_json_schema()
    defs = full_schema.pop("$defs", {})
    if not defs:
        return full_schema
    return _resolve_refs(full_schema, defs)


def _resolve_refs(obj, defs: dict):
    """Recursively resolve $ref references in a JSON schema."""
    if isinstance(obj, dict):
        if "$ref" in obj:
            ref_name = obj["$ref"].split("/")[-1]
            if ref_name in defs:
                resolved = defs[ref_name].copy()
                # Merge any extra keys from the referencing object
                for k, v in obj.items():
                    if k != "$ref":
                        resolved[k] = v
                return _resolve_refs(resolved, defs)
            return obj
        return {k: _resolve_refs(v, defs) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_refs(item, defs) for item in obj]
    return obj
