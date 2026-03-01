# Worker 2d: Balance Sheet Health

Is **{{ticker}}**'s balance sheet healthy?

## Data

- Total Debt: {{total_debt}}
- Total Cash: {{total_cash}}
- Free Cash Flow: {{free_cash_flow}}
- Profit Margins: {{profit_margins}}
- Dividend Yield: {{dividend_yield}}

## Your Task

Write 1-2 sentences on balance sheet health. You MUST cite specific numbers from the data above.

Good example:
```
{
  "assessment": "Healthy balance sheet with $3.2B cash vs $1.8B debt (net cash position of $1.4B) and strong FCF of $890M supporting reinvestment.",
  "evidence": ["Net cash: $3.2B cash vs $1.8B debt = $1.4B net cash", "Free cash flow: $890M annual"]
}
```

Bad example (too vague — do NOT write this):
```
{
  "assessment": "The balance sheet looks fine.",
  "evidence": ["Adequate cash", "Manageable debt"]
}
```

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentences citing specific dollar amounts",
  "evidence": ["specific metric with dollar amount", "specific metric with dollar amount"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING with specific numbers, not an object.
