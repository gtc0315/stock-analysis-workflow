# Step 5b-2: Bear Case

Write the bear case for **{{ticker}}** ({{recommendation}}).

## Risk Factors

- Top risks: {{risk_summary}}
- Concentration risk: {{concentration_risk}}
- Existing holdings: {{existing_holdings}}

## Pre-Computed Downside Facts (you MUST cite these)

- **Stop loss: ${{stop_loss}} = {{stop_technical_basis}}**
- Downside from entry to stop: {{downside_pct}}% = ${{downside_dollars}} loss on ${{position_size}} position
- Next support below stop: {{next_support_below}}

## Your Task

Write a bear case summary in **2-3 sentences**. You MUST include ALL of these:

1. **Name at least one specific risk** (not "market conditions" — name the actual risk)
2. **Quantify the downside** — use the dollar amount or percentage from the facts above
3. **Explain the stop-loss placement** — say "stop at ${{stop_loss}} ({{stop_technical_basis}})" to show it has technical basis

Example: "A stronger dollar or declining industrial demand could push silver below the $75.63 stop at the 50-day SMA, resulting in an 11% loss ($1,650 on the position). If broader commodity weakness materializes, the next support at $70.00 (pivot support) represents a 17.6% drawdown from entry."

## Output

Respond with ONLY a JSON object:

```
{
  "bear_case_summary": "Your 2-3 sentence bear case here..."
}
```
