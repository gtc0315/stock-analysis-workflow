# Worker 1a: Recent News Headlines

What are 3-5 recent news headlines about **{{ticker}}** ({{company_name}})?

For each headline, provide:
- `headline`: a brief news headline text
- `date`: date in YYYY-MM-DD format (use your best estimate)
- `sentiment`: exactly "positive", "negative", or "neutral"

## Output

Respond with ONLY a JSON object:

```
{
  "headlines": [
    {"headline": "...", "date": "YYYY-MM-DD", "sentiment": "positive"},
    ...
  ]
}
```
