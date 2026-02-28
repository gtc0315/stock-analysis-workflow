# Step 5b: Conditions & Narratives

You are writing the investment narrative for **{{ticker}}**.

## Decision Made

- Recommendation: {{recommendation}}
- Confidence: {{confidence}}
- Entry Price: ${{entry_price}}
- Target (base): ${{target_base}}
- Stop Loss: ${{stop_loss}}
- Position Size: ${{position_size}}

## Key Analysis Points

- Fundamental rating: {{fundamental_rating}}
  - Valuation: {{valuation_summary}}
  - Growth: {{growth_summary}}
  - Moat: {{moat_summary}}
  - Balance Sheet: {{balance_sheet_summary}}
- Technical rating: {{technical_rating}}
- Support levels: {{support_levels}}
- Top catalysts: {{catalyst_summary}}
- Top risks: {{risk_summary}}
- Analyst consensus: {{analyst_consensus_summary}}
- Concentration risk: {{concentration_risk}}
- Existing holdings: {{existing_holdings}}

## Your Task

Write four things:

1. **Key Conditions** (2-4 specific, measurable conditions):
   - When should the investor hold this position?
   - When should they exit or reduce?
   - Reference specific events, dates, or price levels

2. **Bull Case Summary** (2-3 sentences):
   - What goes right? Be specific about catalysts and targets.

3. **Bear Case Summary** (2-3 sentences):
   - What goes wrong? Be specific about risks and downside.
   - Include at least one quantified downside (specific price level or % loss)
   - Explain why the stop-loss is placed where it is (e.g., relation to support level)

4. **One-Line Summary** (1 sentence):
   - A single actionable sentence capturing the full recommendation.

## Output Format

Respond with a JSON object:
- key_conditions: [list of 2-4 condition strings]
- bull_case_summary: string (at least 10 characters)
- bear_case_summary: string (at least 10 characters)
- one_line_summary: string (at least 10 characters)
