# Worker 1b: Analyst Consensus

What is the analyst consensus for **{{ticker}}**, currently trading at ${{current_price}}?

Provide your best estimate of:
- Average analyst price target
- Number of buy, hold, and sell ratings

## Output

Respond with ONLY a JSON object:

```
{
  "average_target_price": 420.0,
  "buy_count": 30,
  "hold_count": 5,
  "sell_count": 1
}
```

Use integers for buy_count, hold_count, sell_count. Use a number or null for average_target_price.
