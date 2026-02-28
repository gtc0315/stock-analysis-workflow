# Worker 2b: Growth Assessment

Is **{{ticker}}**'s growth accelerating, stable, or decelerating?

## Data

- Revenue Growth: {{revenue_growth}}
- Earnings Growth: {{earnings_growth}}
- Sector: {{sector}}
- Industry: {{industry}}

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentence summary of growth trajectory",
  "evidence": ["data point 1", "data point 2"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING, not an object.
