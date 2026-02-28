# Step 5a: Recommendation & Price Levels

You are making an investment recommendation for **{{ticker}}**.

## User Risk Profile

- Risk Tolerance: {{risk_tolerance}}
- Time Horizon: {{time_horizon}}
- Position Size Available: ${{position_size_usd}}
- Existing Holdings: {{existing_holdings}}

## Current Market Price

${{current_price}}

## Analysis Summary

### Fundamental Rating: {{fundamental_rating}}
- Valuation: {{valuation_summary}}
- Growth: {{growth_summary}}
- Moat: {{moat_summary}}
- Balance Sheet: {{balance_sheet_summary}}

### Technical Rating: {{technical_rating}}
- Support levels: {{support_levels}}
- Resistance levels: {{resistance_levels}}
- Trend: {{current_trend}}

### Analyst Consensus
{{analyst_consensus_summary}}

### Key Catalysts & Risks
- Catalysts: {{catalyst_summary}}
- Risks: {{risk_summary}}
- Concentration risk: {{concentration_risk}}

## Technical Price Zones (pre-computed from indicators)

These zones are computed deterministically from Bollinger Bands, moving averages, and pivot points. **You MUST anchor your prices to these levels.**

### Stop Zone (below current price, ordered nearest-first)
{{stop_zone}}

### Entry Zone
{{entry_zone}}

### Target Zone (above current price, ordered nearest-first)
{{target_zone}}

## Your Task

Based on the analysis above, provide:

1. **Recommendation**: Exactly one of: buy, hold, sell, avoid
2. **Confidence**: A score from 0.0 to 1.0
3. **Entry Price**: Pick an ideal entry from within the Entry Zone, plus an acceptable range [low, high]
   - **Short horizon**: Entry should be AT or very near the current market price — the question is "should I buy NOW?"
   - **Medium horizon**: A small pullback from current price is acceptable
   - **Long horizon**: You may target a lower entry (limit order) to get a better average cost
4. **Stop Loss**: Pick a stop from the Stop Zone. Choose a level that has technical significance (support, SMA, Bollinger lower). Do NOT invent a round number.
5. **Target Prices**: Pick three targets from the Target Zone in ascending order:
   - Conservative: the nearest resistance/target level above entry
   - Base: a mid-range level from the target zone
   - Optimistic: the furthest level, or the next major resistance beyond
   - If fewer than 3 levels exist in the target zone, space them evenly between the nearest target and the highest target
   - All targets must come from or be interpolated between the levels listed in the Target Zone
6. **Position Size**: Dollar amount to invest (max ${{position_size_usd}})
   - Conservative risk tolerance: recommend ≤ 50% of available
   - Moderate risk tolerance: recommend ≤ 75% of available
   - Aggressive risk tolerance: up to 100% of available

**IMPORTANT**: Every price you output (entry, stop, targets) must be traceable to a technical level in the zones above. If you deviate from a zone level, state which level you're adjusting and why.

## Output Format

Respond with a JSON object containing these fields:
- ticker (string)
- recommendation (string: "buy", "hold", "sell", or "avoid")
- confidence (number: 0.0 to 1.0)
- entry_price: { ideal (number), acceptable_range: [low, high] }
- target_price: { conservative (number), base (number), optimistic (number) }
- stop_loss (number)
- position_size_recommended_usd (number)
