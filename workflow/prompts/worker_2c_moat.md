# Worker 2c: Competitive Moat Assessment

Does **{{ticker}}** ({{company_name}}) have a strong competitive moat?

## Data

- Sector: {{sector}}
- Industry: {{industry}}
- Profit Margins: {{profit_margins}}
- Revenue Growth: {{revenue_growth}}

Consider: pricing power, switching costs, network effects, brand, patents, regulatory barriers.

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentence summary of competitive advantages",
  "evidence": ["data point 1", "data point 2"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING, not an object.
