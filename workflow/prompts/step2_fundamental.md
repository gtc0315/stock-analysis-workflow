# Step 2: Fundamental Analysis

Analyze the fundamentals of **{{ticker}}** based on the data below.

## Data From Step 1

{{step1_output}}

## Your Task

Analyze four dimensions. For each, provide:
- `assessment`: a 1-2 sentence summary (string)
- `evidence`: a list of 2+ strings describing specific data points (e.g., "P/E ratio of 95x is above sector average of 30x")

IMPORTANT: Each evidence item must be a plain text STRING, NOT an object.

### Dimensions

1. **valuation**: Is the stock cheap, fair, or expensive vs sector peers?
2. **growth**: Revenue and earnings growth trajectory (accelerating/stable/decelerating)
3. **moat**: Competitive advantages — pricing power, switching costs, network effects
4. **balance_sheet**: Debt levels, cash position, free cash flow

### Overall Rating

Set `overall_fundamental_rating` to one of: "strong", "moderate", "weak"

## Output

Respond with ONLY a JSON object with these fields:
- `ticker` (string)
- `valuation` (object with `assessment` string and `evidence` array of strings)
- `growth` (object with `assessment` string and `evidence` array of strings)
- `moat` (object with `assessment` string and `evidence` array of strings)
- `balance_sheet` (object with `assessment` string and `evidence` array of strings)
- `overall_fundamental_rating` (string: "strong" or "moderate" or "weak")
