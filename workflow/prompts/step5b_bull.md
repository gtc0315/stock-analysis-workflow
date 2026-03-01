# Step 5b-1: Bull Case

Write the bull case for **{{ticker}}** ({{recommendation}} at {{confidence}} confidence).

## Positive Factors

- Fundamental rating: {{fundamental_rating}}
- Technical rating: {{technical_rating}} ({{current_trend}})
- Top catalysts: {{catalyst_summary}}
- Analyst consensus: {{analyst_consensus_interpretation}}

## Price Context

- Entry: ${{entry_price}}
- Base target: ${{target_base}} (+{{target_upside_pct}}% upside)
- Optimistic target: ${{target_optimistic}}

## Your Task

Write a bull case summary in **2-3 sentences**. Be SPECIFIC:
- Name the catalysts that drive upside (use actual events, not "positive catalysts")
- Reference price targets with dollar amounts
- Explain what supports the entry point

Example: "Silver's industrial demand surge from solar panel manufacturing and EV electronics provides a structural tailwind, with prices targeting $92 at the Bollinger upper band. The bullish MACD crossover and analyst consensus of 71% buy ratings support the $85 entry, while a potential Fed rate pause could drive safe-haven flows toward the $100 resistance."

## Output

Respond with ONLY a JSON object:

```
{
  "bull_case_summary": "Your 2-3 sentence bull case here..."
}
```
