# Step 5b-3: Conditions & Summary

Write key conditions and a one-line summary for **{{ticker}}** ({{recommendation}}).

## Decision Context

- Entry: ${{entry_price}} | Target: ${{target_base}} | Stop: ${{stop_loss}} ({{stop_technical_basis}})
- Time horizon: {{time_horizon}}
- Top catalysts: {{catalyst_summary}}
- Top risks: {{risk_summary}}
- Next earnings: {{next_earnings_date}}

## Your Task

### 1. Key Conditions (2-4 items)

Each condition MUST reference a specific date, price level, or metric. NOT vague.

Good examples:
- "Hold if price stays above $75.63 (50-day SMA)"
- "Reassess after Q1 2025 earnings report"
- "Exit if RSI exceeds 75 (overbought territory)"
- "Reduce position if silver drops below $70 support"

Bad examples (do NOT write these):
- "Hold if market conditions improve" ← too vague
- "Exit if things go wrong" ← no specific trigger

### 2. One-Line Summary (1 sentence)

Must include: **ticker**, **direction** (buy/hold/sell), and **one key reason**.

Example: "Buy SLV at $85 targeting $93 on industrial demand strength with stop at $75.63 (50-day SMA)."

## Output

Respond with ONLY a JSON object:

```
{
  "key_conditions": ["condition 1", "condition 2", "condition 3"],
  "one_line_summary": "One actionable sentence with ticker, direction, and reason."
}
```
