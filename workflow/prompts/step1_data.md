# Step 1: Data Gathering

You are gathering current market data for **{{ticker}}**.

## Your Task

Extract the data points below from the market data provided and organize them into a JSON object.

## Market Data Provided

{{market_data}}

## Required JSON Fields

Use EXACTLY these field names:

- `ticker` (string): "{{ticker}}"
- `current_price` (number): most recent price from the data above
- `price_date` (string): date/time of the price data
- `pe_ratio` (number or null): trailing P/E ratio
- `ps_ratio` (number or null): trailing P/S ratio
- `market_cap_billions` (number): market cap in billions USD
- `week_52_high` (number): 52-week high price
- `week_52_low` (number): 52-week low price
- `beta` (number or null): stock beta
- `short_interest_pct` (number or null): short interest as % of float
- `recent_news` (array): 3-5 recent headlines, each with:
  - `headline` (string): news headline
  - `date` (string): date in YYYY-MM-DD format
  - `sentiment` (string): "positive" or "negative" or "neutral"
- `next_earnings_date` (string or null): upcoming earnings date
- `analyst_consensus` (object or null): analyst ratings with EXACTLY these fields:
  - `average_target_price` (number or null): average target price
  - `buy_count` (integer): number of buy ratings
  - `hold_count` (integer): number of hold ratings
  - `sell_count` (integer): number of sell ratings
- `data_retrieval_timestamp` (string): current ISO timestamp

## Data Sources

Use the provided market data as your primary source. Supplement with your knowledge for analyst ratings and recent news.

## Output

Respond with ONLY the JSON object. No explanation or commentary.
