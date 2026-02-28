# Worker 3b: Catalyst Identification

List 3-4 upcoming catalysts that could move **{{ticker}}** ({{company_name}}) stock price higher.

## Context

- Sector: {{sector}}
- Industry: {{industry}}
- Next Earnings Date: {{next_earnings_date}}

Consider: earnings reports, product launches, partnerships, regulatory changes, macro events, contract wins.

## Output

Respond with ONLY a JSON object:

```
{
  "catalysts": [
    {"event": "description of catalyst", "expected_date": "2025-Q1", "impact": "positive", "magnitude": "high"},
    {"event": "another catalyst", "expected_date": null, "impact": "positive", "magnitude": "medium"}
  ]
}
```

Rules:
- `impact` must always be "positive"
- `magnitude` must be "high", "medium", or "low"
- `expected_date` can be a date string or null
