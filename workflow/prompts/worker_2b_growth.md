# Worker 2b: Growth Assessment

Is **{{ticker}}**'s growth accelerating, stable, or decelerating?

## Data

- Revenue Growth: {{revenue_growth}}
- Earnings Growth: {{earnings_growth}}
- Sector: {{sector}}
- Industry: {{industry}}

## Your Task

Write 1-2 sentences on growth trajectory. You MUST cite specific numbers from the data above.

Good example:
```
{
  "assessment": "Revenue growing at 14.2% with earnings accelerating at 28.5%, outpacing the Software sector average of ~10% revenue growth.",
  "evidence": ["Revenue growth: 14.2% YoY", "Earnings growth: 28.5% YoY (accelerating)"]
}
```

Bad example (too vague — do NOT write this):
```
{
  "assessment": "Growth is moderate.",
  "evidence": ["Decent growth", "Stable trajectory"]
}
```

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentences citing specific growth numbers",
  "evidence": ["specific metric with number", "specific metric with number"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING with a specific number, not an object.
