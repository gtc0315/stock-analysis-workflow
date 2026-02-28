# Worker 3c: Risk Identification

List 3-4 key risks for **{{ticker}}** ({{company_name}}).

## Context

- Sector: {{sector}}
- Industry: {{industry}}
- Current Price: ${{current_price}}
- Market Cap: ${{market_cap_billions}}B

Consider: competition, macro headwinds, regulatory risks, customer concentration, technology disruption, execution risk, valuation risk.

## Output

Respond with ONLY a JSON object:

```
{
  "risks": [
    {"event": "description of risk", "expected_date": null, "impact": "negative", "magnitude": "high"},
    {"event": "another risk", "expected_date": null, "impact": "negative", "magnitude": "medium"}
  ]
}
```

Rules:
- `impact` must always be "negative"
- `magnitude` must be "high", "medium", or "low"
- `expected_date` can be a date string or null
