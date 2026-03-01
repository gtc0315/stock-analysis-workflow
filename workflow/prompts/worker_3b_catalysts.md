# Worker 3b: Catalyst Identification

List 3-4 upcoming catalysts that could move **{{ticker}}** ({{company_name}}) stock price higher.

## Context

- Sector: {{sector}}
- Industry: {{industry}}
- Next Earnings Date: {{next_earnings_date}}

## Your Task

List 3-4 catalysts from DIFFERENT categories. Each must be a specific, named event.

IMPORTANT: Catalysts must span at least 2 different categories. Pick from:
- Earnings (quarterly reports, guidance revisions)
- Product (launches, new features, platform updates)
- Regulatory (FDA approvals, government policy, compliance changes)
- Partnerships/M&A (deals, contracts, acquisitions)
- Macro (Fed rates, commodity prices, sector tailwinds)

Good example:
```
{
  "catalysts": [
    {"event": "Q1 2025 earnings report expected to show 20%+ revenue growth continuation", "expected_date": "2025-03-15", "impact": "positive", "magnitude": "high"},
    {"event": "New FedRAMP certification could unlock $2B government security market", "expected_date": "2025-Q2", "impact": "positive", "magnitude": "medium"},
    {"event": "Potential Fed rate cut would boost growth stock multiples", "expected_date": null, "impact": "positive", "magnitude": "medium"}
  ]
}
```

Bad example (all same category — do NOT write this):
```
{
  "catalysts": [
    {"event": "Good earnings", "expected_date": null, "impact": "positive", "magnitude": "high"},
    {"event": "Better guidance", "expected_date": null, "impact": "positive", "magnitude": "medium"},
    {"event": "Revenue beat", "expected_date": null, "impact": "positive", "magnitude": "medium"}
  ]
}
```

## Output

Respond with ONLY a JSON object with `catalysts` array. Rules:
- `impact` must always be "positive"
- `magnitude` must be "high", "medium", or "low"
- `expected_date` can be a date string or null
