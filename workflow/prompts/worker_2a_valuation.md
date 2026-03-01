# Worker 2a: Valuation Assessment

Is **{{ticker}}** cheap, fair, or expensive relative to its sector peers?

## Data

- Current Price: ${{current_price}}
- P/E Ratio (trailing): {{pe_ratio}}
- Forward P/E: {{forward_pe}}
- P/S Ratio: {{ps_ratio}}
- Market Cap: ${{market_cap_billions}}B
- 52-Week High: ${{week_52_high}}
- 52-Week Low: ${{week_52_low}}
- Sector: {{sector}}

## Your Task

Write 1-2 sentences assessing valuation. You MUST cite specific numbers from the data above.

Good example:
```
{
  "assessment": "Trading at a P/E of 28.3x vs the Technology sector average of ~22x, slightly premium but justified by forward P/E of 19.5x.",
  "evidence": ["Trailing P/E of 28.3x vs sector avg ~22x", "Forward P/E of 19.5x implies earnings catch-up", "At 87% of 52-week high ($210 vs $241)"]
}
```

Bad example (too vague — do NOT write this):
```
{
  "assessment": "The stock appears fairly valued.",
  "evidence": ["Reasonable valuation", "In line with peers"]
}
```

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentences citing specific metrics from the data",
  "evidence": ["metric: value (with comparison)", "metric: value", "metric: value"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING with a specific number, not an object.
