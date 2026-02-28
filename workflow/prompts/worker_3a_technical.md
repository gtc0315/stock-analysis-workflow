# Worker 3a: Technical Interpretation

Based on the pre-computed technical indicators below, is the technical picture for **{{ticker}}** bullish, neutral, or bearish?

## Pre-Computed Technical Indicators

- Current Price: ${{current_price}}
- RSI (14-day): {{rsi}} ({{rsi_signal}})
- MACD Direction: {{macd_direction}} (histogram: {{macd_histogram}})
- Computed Trend: {{trend}}
- SMA-50: {{sma_50}} (price is {{price_vs_50_sma}} SMA-50)
- SMA-200: {{sma_200}} (price is {{price_vs_200_sma}} SMA-200)
- Golden Cross: {{golden_cross}}
- Bollinger Bands (20,2): Upper={{bollinger_upper}}, Middle={{bollinger_middle}}, Lower={{bollinger_lower}}
- Bollinger %B: {{bollinger_pct_b}} (0=at lower band, 1=at upper band)
- Volume: {{volume_assessment}} (5d/30d ratio: {{volume_ratio}})

## Output

Respond with ONLY a JSON object:

```
{
  "current_trend": "uptrend",
  "overall_technical_rating": "bullish",
  "volume_analysis": "1-2 sentences interpreting volume activity"
}
```

Use EXACTLY one of: "uptrend", "downtrend", "consolidation" for current_trend.
Use EXACTLY one of: "bullish", "neutral", "bearish" for overall_technical_rating.
