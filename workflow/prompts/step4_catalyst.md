# Step 4: Catalyst & Risk Identification

You are identifying catalysts and risks for **{{ticker}}**.

## Data From Previous Steps

{{step1_output}}
{{step2_output}}
{{step3_output}}

## User's Existing Holdings

{{existing_holdings}}

## Your Task

### 1. Upcoming Catalysts
Identify at least 3 potential catalysts that could move the stock price. For each:
- Describe the event
- Estimate when it might happen (if known)
- Classify impact as positive or negative
- Rate magnitude as high, medium, or low

Consider: earnings reports, product launches, FDA approvals, regulatory changes, macro events, sector rotation, management changes, M&A potential.

### 2. Key Risks
Identify at least 3 material risks. For each:
- Describe the risk
- Classify impact as negative
- Rate magnitude as high, medium, or low

Consider: competitive threats, macro headwinds, regulatory risks, customer concentration, technology disruption, execution risk, valuation risk.

### 3. Correlation with Existing Holdings
If the user has existing holdings:
- Assess how correlated this stock is with their current portfolio
- Flag if adding this stock increases sector or factor concentration
- Set `concentration_risk_flag` to true if all/most holdings are in the same sector

## Output Format

Respond with a JSON object matching the CatalystRiskOutput schema.
