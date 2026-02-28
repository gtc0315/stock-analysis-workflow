# Step 3: Technical Analysis

You are performing technical analysis on **{{ticker}}**.

## Data From Previous Steps

{{step1_output}}

## Your Task

Analyze the stock's technical picture across these dimensions:

### 1. Current Trend
- Classify as uptrend, downtrend, or consolidation
- Reference moving averages (50-day, 200-day) relative to price

### 2. Key Support and Resistance Levels
- Identify at least 3 support levels (prices where buying pressure has historically emerged)
- Identify at least 3 resistance levels (prices where selling pressure has historically emerged)
- Base these on recent price action, round numbers, and previous pivot points

### 3. Momentum Indicators
- RSI (14-period): value and whether oversold (<30), neutral (30-70), or overbought (>70)
- MACD direction: bullish crossover, bearish crossover, or neutral

### 4. Volume Analysis
- Is recent volume above or below the average?
- Any notable volume divergences (price up on low volume = weak, etc.)

## Output Format

Respond with a JSON object matching the TechnicalAnalysisOutput schema. Provide an `overall_technical_rating` of "bullish", "neutral", or "bearish".
