# Worker 2d: Balance Sheet Health

Is **{{ticker}}**'s balance sheet healthy?

## Data

- Total Debt: {{total_debt}}
- Total Cash: {{total_cash}}
- Free Cash Flow: {{free_cash_flow}}
- Profit Margins: {{profit_margins}}
- Dividend Yield: {{dividend_yield}}

## Output

Respond with ONLY a JSON object:

```
{
  "assessment": "1-2 sentence summary of balance sheet health",
  "evidence": ["data point 1", "data point 2"]
}
```

IMPORTANT: Each evidence item must be a plain text STRING, not an object.
