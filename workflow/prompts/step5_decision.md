# Step 5: Decision Synthesis

You are synthesizing all analysis into a final investment recommendation for **{{ticker}}**.

## User Risk Profile

- Risk Tolerance: {{risk_tolerance}}
- Time Horizon: {{time_horizon}}
- Position Size Available: ${{position_size_usd}}
- Existing Holdings: {{existing_holdings}}

## Analysis From Previous Steps

### Step 1 - Market Data
{{step1_output}}

### Step 2 - Fundamental Analysis
{{step2_output}}

### Step 3 - Technical Analysis
{{step3_output}}

### Step 4 - Catalysts & Risks
{{step4_output}}

## Your Task

Synthesize ALL of the above into a single actionable recommendation. You MUST:

1. **Recommendation**: Choose exactly one of: buy, hold, sell, avoid
2. **Confidence**: Score 0.0 to 1.0 reflecting your conviction level
3. **Entry Price**: Set an ideal entry price and acceptable range based on technical levels
4. **Target Prices**: Set conservative, base, and optimistic targets. These MUST be in ascending order.
5. **Stop Loss**: Set below key support. Must be below entry price.
6. **Position Size**: Recommend a dollar amount ≤ the user's available amount, calibrated to their risk tolerance
7. **Risk/Reward Ratio**: Calculate as (target_base - entry_ideal) / (entry_ideal - stop_loss)
8. **Key Conditions**: List 2-4 specific, measurable conditions for holding/exiting
9. **Bull & Bear Cases**: Write concise summaries of both scenarios
10. **One-Line Summary**: A single actionable sentence

## Calibration Rules

- **Conservative** investors: position size ≤ 50% of available, stop loss within 10% of entry
- **Moderate** investors: position size ≤ 75% of available, stop loss within 15% of entry
- **Aggressive** investors: position size up to 100% of available, wider stops acceptable

- **Short horizon**: focus on technical setups and near-term catalysts
- **Medium horizon**: balance fundamental and technical
- **Long horizon**: weight fundamentals more heavily

## Output Format

Respond with a JSON object matching the DecisionOutput schema. All prices must be realistic relative to the current market price.
