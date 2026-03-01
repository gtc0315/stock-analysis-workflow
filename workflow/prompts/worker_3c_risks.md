# Worker 3c: Risk Identification

List 3-4 key risks for **{{ticker}}** ({{company_name}}).

## Context

- Sector: {{sector}}
- Industry: {{industry}}
- Current Price: ${{current_price}}
- Market Cap: ${{market_cap_billions}}B

## Your Task

List 3-4 risks from DIFFERENT categories. Each must be specific and named.

IMPORTANT: Risks must span at least 2 different categories. Pick from:
- Competitive (market share loss, new entrants, pricing pressure)
- Macro (recession, inflation, interest rates, currency, tariffs)
- Regulatory (government action, lawsuits, compliance costs)
- Execution (management, operational failures, supply chain)
- Valuation (overvalued, multiple compression, bubble risk)
- Technical (technology disruption, obsolescence)

Good example:
```
{
  "risks": [
    {"event": "Increasing competition from Microsoft Sentinel could pressure market share in cloud security", "expected_date": null, "impact": "negative", "magnitude": "high"},
    {"event": "Potential recession would slow enterprise IT spending, reducing new contract wins", "expected_date": null, "impact": "negative", "magnitude": "medium"},
    {"event": "Trading at 85x trailing P/E creates vulnerability to any earnings miss or guidance cut", "expected_date": null, "impact": "negative", "magnitude": "high"}
  ]
}
```

Bad example (all same category — do NOT write this):
```
{
  "risks": [
    {"event": "Market risk", "expected_date": null, "impact": "negative", "magnitude": "medium"},
    {"event": "Economic downturn", "expected_date": null, "impact": "negative", "magnitude": "medium"},
    {"event": "Recession fears", "expected_date": null, "impact": "negative", "magnitude": "medium"}
  ]
}
```

## Output

Respond with ONLY a JSON object with `risks` array. Rules:
- `impact` must always be "negative"
- `magnitude` must be "high", "medium", or "low"
- `expected_date` can be a date string or null
