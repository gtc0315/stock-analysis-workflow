# Stock Analysis Evaluation Rubric (Sub-Item Scoring)

You are an expert financial analyst evaluating the quality of a stock analysis report.
For each dimension below, evaluate every sub-item as PASS (true) or FAIL (false).
Provide a brief note (1 sentence max) justifying each judgment.

Be rigorous — only mark `"met": true` if the criterion is clearly satisfied.

## Dimensions and Sub-Items

### 1. Causal Reasoning (Weight: 25%)

Evaluate whether conclusions are properly supported by evidence.

- **metrics_cited**: Fundamental assessments reference specific numbers (P/E, growth %, FCF, etc.), not vague claims like "valuation looks reasonable"
- **technical_alignment**: Technical interpretation is consistent with the actual indicator values provided (e.g., if RSI > 70, analysis should note overbought; if MACD is bearish, should not claim bullish momentum)
- **recommendation_follows_evidence**: The final recommendation (buy/hold/sell/avoid) logically follows from the combined fundamental, technical, and catalyst evidence
- **confidence_calibrated**: The confidence level matches the strength/ambiguity of evidence (mixed signals should not produce >0.8 confidence; strong unanimous signals should not produce <0.4). Also FAIL if high confidence (>0.7) accompanies extreme price targets — predicting a stock will double with 80% confidence is overconfident by definition
- **counterarguments_present**: The analysis acknowledges at least one potential weakness or counter-argument to its own thesis

### 2. Information Completeness (Weight: 25%)

Evaluate whether all material facts are covered.

- **news_substantive**: News items reference specific events or announcements with approximate dates, not generic filler like "market conditions improving"
- **earnings_discussed**: Next earnings date or most recent earnings results are explicitly mentioned somewhere in the analysis. If no earnings date is available in the data (next_earnings_date is null), this item passes automatically — the analysis cannot discuss what the data source didn't provide
- **analyst_consensus_interpreted**: Analyst consensus data is present AND contextualized (not just raw numbers — the analysis explains what the consensus implies)
- **catalyst_variety**: Catalysts span at least 2 different categories (e.g., earnings + product launch, or regulatory + partnership — not all from the same category)
- **risk_variety**: Risks span at least 2 different categories (e.g., competitive + regulatory, or macro + execution — not all from the same category)
- **bull_bear_balanced**: Both bull and bear case summaries are substantive (each at least 2 sentences) and roughly equal in depth and effort

### 3. Actionability (Weight: 20%)

Evaluate whether the reader can execute immediately.

- **entry_range_justified**: Entry price includes both an ideal price AND an acceptable range, and these relate to current market levels (not arbitrary round numbers disconnected from the stock price)
- **targets_tiered_and_realistic**: Three price targets (conservative, base, optimistic) are present with a reasonable spread that reflects genuine uncertainty. FAIL if the base target implies a move that would be extraordinary for this asset class — for example, a base target that more than doubles the current price is almost never realistic for a short/medium horizon. Compare the implied upside to what this type of stock/ETF realistically moves
- **stop_loss_technical_basis**: The stop-loss level connects to a support level, moving average, or other technical rationale — not just an arbitrary percentage or round number
- **conditions_measurable**: Key conditions for the trade reference specific dates, price levels, or measurable metrics (not vague like "if the market improves")
- **summary_standalone**: The one-line summary contains the ticker, direction (buy/hold/sell), and at least one key reason — it is actionable on its own

### 4. Risk Awareness (Weight: 20%)

Evaluate whether risks are taken seriously.

- **diverse_risk_categories**: Risks come from at least 2 distinct categories (e.g., competitive, regulatory, macro, execution, technical)
- **bear_case_detailed**: The bear case includes specific catalysts and price implications (e.g., "if earnings miss, could fall to $X"), not just vague warnings
- **stop_loss_explained**: The stop-loss placement has an explained rationale (e.g., "below key support at $X") rather than appearing as an arbitrary number
- **portfolio_impact_discussed**: How this position affects the overall portfolio or interacts with existing holdings is discussed (correlation, concentration, diversification). If the user has no existing holdings (existing_holdings is empty or "None"), this item passes if the analysis mentions general diversification or portfolio allocation, even without specific holdings correlation
- **downside_scenario_quantified**: At least one specific downside scenario includes a quantified magnitude (dollar amount or percentage loss)

### 5. User Appropriateness (Weight: 10%)

Evaluate whether the analysis is calibrated to the user's profile.

- **position_size_appropriate**: The recommended position size respects the user's stated risk tolerance level (conservative ≤ 50%, moderate ≤ 75%, aggressive ≤ 100% of available capital)
- **time_horizon_matched**: Price targets and conditions align with the user's stated time horizon (short/medium/long). FAIL if a short-horizon analysis sets targets that would require a multi-year move to reach, or if a long-horizon analysis only discusses next-week catalysts. The magnitude of expected price movement must be plausible within the stated timeframe
- **holdings_correlation_noted**: If the user has existing holdings, the analysis discusses how this position correlates with or impacts those holdings
- **tone_matches_profile**: The overall analysis tone is appropriate for the user's risk profile (not overly aggressive for conservative, not overly cautious for aggressive)

## Output Format

Respond ONLY with a JSON object. For each dimension, provide each sub-item with `met` (boolean) and `note` (brief string).

Do NOT include dimension-level scores, overall scores, or a `passed` field. Only provide sub-items.

```json
{
  "causal_reasoning": {
    "metrics_cited": {"met": true, "note": "P/E of 95x and revenue growth of 33% cited in valuation"},
    "technical_alignment": {"met": true, "note": "Bullish rating matches uptrend and neutral RSI of 58"},
    "recommendation_follows_evidence": {"met": true, "note": "Buy supported by strong growth, wide moat, and bullish technicals"},
    "confidence_calibrated": {"met": true, "note": "0.72 appropriate for strong fundamentals but elevated valuation"},
    "counterarguments_present": {"met": true, "note": "Bear case acknowledges outage litigation and valuation risk"}
  },
  "information_completeness": {
    "news_substantive": {"met": true, "note": "3 news items with specific dates and named events"},
    "earnings_discussed": {"met": true, "note": "Next earnings March 4 mentioned in catalysts"},
    "analyst_consensus_interpreted": {"met": false, "note": "Raw buy/hold/sell counts present but no interpretation of what consensus implies"},
    "catalyst_variety": {"met": true, "note": "Earnings + federal mandate + platform expansion across 3 categories"},
    "risk_variety": {"met": true, "note": "Litigation + valuation + competitive risks across 3 categories"},
    "bull_bear_balanced": {"met": true, "note": "Both cases are 3 sentences with specific catalysts and price levels"}
  },
  "actionability": {
    "entry_range_justified": {"met": true, "note": "Ideal $370 with range $360-385 near current price and support"},
    "targets_tiered_and_realistic": {"met": true, "note": "$430/$520/$620 spread reflects uncertainty from litigation"},
    "stop_loss_technical_basis": {"met": true, "note": "Stop at $330 below key support and 200-day SMA"},
    "conditions_measurable": {"met": true, "note": "March 4 earnings ARR target, $330 price level, litigation $500M threshold"},
    "summary_standalone": {"met": true, "note": "Contains CRWD, buy, $370 entry, $520 target, and risk-reward ratio"}
  },
  "risk_awareness": {
    "diverse_risk_categories": {"met": true, "note": "Litigation + valuation + competition across 3 categories"},
    "bear_case_detailed": {"met": true, "note": "Specifies outage impact, multiple compression to $300-330 range"},
    "stop_loss_explained": {"met": false, "note": "Stop at $330 stated but no explicit connection to support level"},
    "portfolio_impact_discussed": {"met": true, "note": "Concentration risk flagged for 100% tech portfolio"},
    "downside_scenario_quantified": {"met": true, "note": "Bear case specifies $300-330 range, roughly 10-20% downside"}
  },
  "user_appropriateness": {
    "position_size_appropriate": {"met": true, "note": "$7500 is 75% of $10K, within moderate investor limit"},
    "time_horizon_matched": {"met": true, "note": "Medium-term targets align with stated medium time horizon"},
    "holdings_correlation_noted": {"met": true, "note": "CRWD correlation with existing tech holdings discussed"},
    "tone_matches_profile": {"met": true, "note": "Balanced tone with clear risk warnings fits moderate profile"}
  }
}
```
