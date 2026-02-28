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

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentence summary of valuation",
  "evidence": ["data point 1", "data point 2", "data point 3"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING, not an object.
