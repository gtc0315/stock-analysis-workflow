# Worker 2c: Competitive Moat Assessment

Does **{{ticker}}** ({{company_name}}) have a strong competitive moat?

## Data

- Sector: {{sector}}
- Industry: {{industry}}
- Profit Margins: {{profit_margins}}
- Revenue Growth: {{revenue_growth}}

Consider: pricing power, switching costs, network effects, brand, patents, regulatory barriers.

## Your Task

Write 1-2 sentences on competitive advantages. Be SPECIFIC about what type of moat exists.

Good example:
```
{
  "assessment": "Strong wide moat from high switching costs and 75.2% gross margins, indicating significant pricing power in the cybersecurity market.",
  "evidence": ["Profit margins of 75.2% suggest strong pricing power", "High switching costs: enterprise security platforms are deeply integrated"]
}
```

Bad example (too vague — do NOT write this):
```
{
  "assessment": "The company has some competitive advantages.",
  "evidence": ["Good market position", "Known brand"]
}
```

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentences naming specific moat types and citing margins/growth",
  "evidence": ["specific advantage with supporting data", "specific advantage with supporting data"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING, not an object.
