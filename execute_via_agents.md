# Execute Stock Analysis via Session Agents

Run the full stock analysis pipeline using Claude Code session agents as LLM
workers. This produces the same `AnalysisResult` and `EvalReport` as the
normal `python workflow/runner.py` path, but replaces API-based LLM calls with
the Agent tool. All deterministic code (Phase 0, Phase 5, Layer 1 eval) runs
from the **same source files** — only the LLM invocation method differs.

---

## Step 0 — Collect User Inputs

**Ask the user** (use `AskUserQuestion`) for the following before proceeding:

| Input               | Description                             | Example       |
|---------------------|-----------------------------------------|---------------|
| `ticker`            | Stock / ETF ticker symbol               | `AAPL`        |
| `risk_tolerance`    | `conservative`, `moderate`, `aggressive` | `moderate`    |
| `time_horizon`      | `short`, `medium`, `long`               | `medium`      |
| `position_size_usd` | Dollar budget for this trade            | `10000`       |
| `existing_holdings` | Comma-separated tickers (or empty)      | `MSFT, GOOG`  |

Store these as variables for all subsequent steps.

---

## Step 1 — Phase 0: Deterministic Data Gathering

Phase 0 is **code-only** — no LLM needed.

### 1a. Fetch market data

Use `WebSearch` to gather current data for `{ticker}`:

```
query: "{ticker} stock price 52 week high low beta market cap key statistics {current_year}"
```

Extract and record:
- `current_price`, `previous_close`
- `pe_ratio`, `forward_pe`, `ps_ratio` (null if ETF/commodity)
- `market_cap_billions`, `week_52_high`, `week_52_low`
- `beta`, `short_interest_pct`
- `sector`, `industry`, `company_name`
- `revenue_growth`, `earnings_growth`, `profit_margins`
- `total_debt`, `total_cash`, `free_cash_flow`
- `dividend_yield`, `fifty_day_average`, `two_hundred_day_average`
- `next_earnings_date`

### 1b. Fetch technical indicators

Use `WebSearch`:

```
query: "{ticker} technical analysis RSI MACD 50-day 200-day moving average support resistance {current_year}"
```

Extract and record:
- `rsi`, `rsi_signal` (oversold/neutral/overbought)
- `macd_direction` (bullish/neutral/bearish), `macd_histogram`
- `sma_50`, `sma_200`
- `price_vs_50_sma` (above/below), `price_vs_200_sma` (above/below)
- `golden_cross` (bool)
- `bollinger_upper`, `bollinger_middle`, `bollinger_lower`, `bollinger_pct_b`
- `trend` (uptrend/downtrend/consolidation)
- `volume_assessment`, `volume_ratio`
- `support_candidates` (list of price levels)
- `resistance_candidates` (list of price levels)

### 1c. Build Phase 0 structures

Run `Bash`:

```python
python3 << 'PYEOF'
import json, sys
sys.path.insert(0, '.')
from workflow.runner import _build_data_gathering_base, _compute_price_zones
from workflow.concentration import check_sector_concentration

market_data = {  # ← Paste gathered data here
    "ticker": "TICKER",
    "current_price": 0.0,
    # ... all fields from 1a ...
}

tech_indicators = {  # ← Paste gathered data here
    "rsi": None,
    # ... all fields from 1b ...
}

step1_base = _build_data_gathering_base(market_data)
current_price = step1_base["current_price"]

price_zones = _compute_price_zones(current_price, tech_indicators, "TIME_HORIZON")

concentration = check_sector_concentration(
    "TICKER", market_data.get("sector", "Unknown"), ["EXISTING", "HOLDINGS"]
)

# Save for later phases
import pickle
with open("/tmp/phase0.pkl", "wb") as f:
    pickle.dump({
        "market_data": market_data,
        "step1_base": step1_base,
        "tech_indicators": tech_indicators,
        "price_zones": price_zones,
        "concentration": concentration,
        "current_price": current_price,
    }, f)

print(json.dumps({"current_price": current_price,
                   "price_zones": price_zones,
                   "concentration": concentration}, indent=2, default=str))
PYEOF
```

---

## Step 2 — Phase 1-3: Parallel LLM Workers (9 Agents)

Launch **all 9 agents in parallel** using the `Agent` tool. Each agent acts as
one LLM worker from the pipeline.

### System prompt (same for all workers)

Read `workflow/prompts/system.md` — use its content as the system instruction
prefix for every agent prompt below.

### Worker prompts

Fill the `{{placeholders}}` using data from Phase 0. The prompt templates live
in `workflow/prompts/worker_*.md`. Use the same variable substitutions that
`runner.py:_build_worker_prompts()` performs.

| Agent | Prompt File | Model | Key Inputs |
|-------|-------------|-------|------------|
| 1a News | `worker_1a_news.md` | haiku | `ticker`, `company_name` |
| 1b Analyst | `worker_1b_analyst.md` | haiku | `ticker`, `current_price` |
| 2a Valuation | `worker_2a_valuation.md` | haiku | `ticker`, price, ratios, market cap, 52w range, sector |
| 2b Growth | `worker_2b_growth.md` | haiku | `ticker`, revenue/earnings growth, sector, industry |
| 2c Moat | `worker_2c_moat.md` | haiku | `ticker`, `company_name`, sector, industry, margins, growth |
| 2d Balance | `worker_2d_balance.md` | haiku | `ticker`, debt, cash, FCF, margins, dividend yield |
| 3a Technical | `worker_3a_technical.md` | haiku | `ticker`, all tech indicator fields |
| 3b Catalysts | `worker_3b_catalysts.md` | haiku | `ticker`, `company_name`, sector, industry, next earnings |
| 3c Risks | `worker_3c_risks.md` | haiku | `ticker`, `company_name`, sector, industry, price, market cap |

**Instructions for each agent call:**
1. Prefix the filled prompt with the system prompt content.
2. Set `model: haiku` for cost/speed.
3. Set `max_turns: 1` (single-shot, no tool use needed).
4. Tell the agent: "Respond with ONLY a JSON object. No markdown fences."
5. Parse the returned JSON into the worker result dict.

### Assemble intermediate results

After all 9 agents return, run `Bash`:

```python
python3 << 'PYEOF'
import json, sys, pickle
sys.path.insert(0, '.')
from workflow.runner import _assemble_step1, _assemble_step2, _assemble_step3, _assemble_step4

with open("/tmp/phase0.pkl", "rb") as f:
    p0 = pickle.load(f)

worker_results = {  # ← Paste all 9 agent JSON outputs here
    "1a_news": { ... },
    "1b_analyst": { ... },
    "2a_valuation": { ... },
    "2b_growth": { ... },
    "2c_moat": { ... },
    "2d_balance": { ... },
    "3a_technical": { ... },
    "3b_catalysts": { ... },
    "3c_risks": { ... },
}

step1_result = _assemble_step1(p0["step1_base"], worker_results)
step2_result = _assemble_step2(p0["market_data"]["ticker"], worker_results)
step3_result = _assemble_step3(p0["market_data"]["ticker"], p0["tech_indicators"], worker_results)
step4_result = _assemble_step4(p0["market_data"]["ticker"], worker_results, p0["concentration"])

with open("/tmp/phase1_3.pkl", "wb") as f:
    pickle.dump({
        "step1_result": step1_result,
        "step2_result": step2_result,
        "step3_result": step3_result,
        "step4_result": step4_result,
        "worker_results": worker_results,
    }, f)

print("Assembled. Fundamental rating:", step2_result.get("overall_fundamental_rating"))
print("Technical rating:", step3_result.get("overall_technical_rating"))
PYEOF
```

---

## Step 3 — Phase 4: Recommendation + Narrative (2 Sequential Agents)

These run **sequentially** — Phase 4b depends on Phase 4a output.

### 4a. Recommendation (Agent, model: opus or sonnet)

Read `workflow/prompts/step5a_recommendation.md` and fill all `{{placeholders}}`
using the assembled step1-step4 results and price zones from Phase 0.

The key variables to fill (see `runner.py` lines 1641-1665):
- Risk profile fields: `risk_tolerance`, `time_horizon`, `position_size_usd`, `existing_holdings`
- `current_price`
- Fundamental: `fundamental_rating`, `valuation_summary`, `growth_summary`, `moat_summary`, `balance_sheet_summary`
- Technical: `technical_rating`, `support_levels`, `resistance_levels`, `current_trend`
- `analyst_consensus_summary` (build from step1 analyst consensus data)
- `catalyst_summary`, `risk_summary` (semicolon-joined from step4)
- `concentration_risk`
- Price zones: `stop_zone`, `entry_zone`, `target_zone` (formatted as bullet lists)

Launch an `Agent` with `model: opus` (or `sonnet`), `max_turns: 1`.
Parse the JSON output as `step5a_result`.

### 4b. Narrative (Agent, model: opus or sonnet)

Read `workflow/prompts/step5b_narrative.md` and fill `{{placeholders}}` using
the step5a result plus the same analysis summaries.

The key variables to fill (see `runner.py` lines 1677-1698):
- `ticker`, `recommendation`, `confidence`, `entry_price`, `target_base`, `stop_loss`, `position_size`
- Same fundamental/technical/catalyst/risk summaries as 4a
- `analyst_consensus_summary`, `concentration_risk`, `existing_holdings`

Launch an `Agent` with `model: opus` (or `sonnet`), `max_turns: 1`.
Parse the JSON output as `step5b_result`.

---

## Step 4 — Phase 5: Deterministic Assembly

Run `Bash` — this is **pure code**, same as the normal pipeline:

```python
python3 << 'PYEOF'
import json, sys, pickle
sys.path.insert(0, '.')
from workflow.runner import _assemble_decision
from workflow.schema import (
    AnalysisResult, DataGatheringOutput, FundamentalAnalysisOutput,
    TechnicalAnalysisOutput, CatalystRiskOutput, DecisionOutput, RiskProfile
)
from datetime import datetime
from pathlib import Path

with open("/tmp/phase0.pkl", "rb") as f:
    p0 = pickle.load(f)
with open("/tmp/phase1_3.pkl", "rb") as f:
    p13 = pickle.load(f)

step5a_result = { ... }  # ← Paste Phase 4a JSON
step5b_result = { ... }  # ← Paste Phase 4b JSON

risk_profile = RiskProfile(
    risk_tolerance="RISK_TOLERANCE",
    time_horizon="TIME_HORIZON",
    position_size_usd=POSITION_SIZE,
    existing_holdings=["HOLDINGS"],
)

fund_rating = p13["step2_result"].get("overall_fundamental_rating", "moderate")
step5_result = _assemble_decision(
    step5a_result, step5b_result, risk_profile,
    p13["step1_result"], p0["price_zones"], fund_rating
)

result = AnalysisResult(
    ticker="TICKER",
    risk_profile=risk_profile,
    model_name="claude-opus-4-6",
    timestamp=datetime.now().isoformat(),
    step1_data=DataGatheringOutput.model_validate(p13["step1_result"]),
    step2_fundamental=FundamentalAnalysisOutput.model_validate(p13["step2_result"]),
    step3_technical=TechnicalAnalysisOutput.model_validate(p13["step3_result"]),
    step4_catalysts=CatalystRiskOutput.model_validate(p13["step4_result"]),
    step5_decision=DecisionOutput.model_validate(step5_result),
)

results_dir = Path("results")
results_dir.mkdir(exist_ok=True)
result_path = results_dir / f'{result.ticker}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(result_path, "w") as f:
    json.dump(result.model_dump(), f, indent=2, default=str)

# Save for eval
with open("/tmp/agent_result.json", "w") as f:
    json.dump(result.model_dump(), f, indent=2, default=str)

d = step5_result
print(f"Saved: {result_path}")
print(f"Recommendation: {d['recommendation'].upper()} @ {d['confidence']:.0%} confidence")
print(f"Entry: ${d['entry_price']['ideal']:.2f}  Stop: ${d['stop_loss']:.2f}")
print(f"Targets: ${d['target_price']['conservative']:.2f} / ${d['target_price']['base']:.2f} / ${d['target_price']['optimistic']:.2f}")
print(f"Position: ${d['position_size_recommended_usd']:,.0f} ({d['position_size_pct_of_input']:.0%})")
print(f"R:R {d['risk_reward_ratio']:.2f}x | {d['time_horizon']} horizon")
PYEOF
```

---

## Step 5 — Eval: Layer 1 (Deterministic) + Layer 2 (Judge Agents)

### 5a. Layer 1 — deterministic checks (code)

```python
python3 << 'PYEOF'
import json, sys
sys.path.insert(0, '.')
from eval.layer1_deterministic import run_layer1
from eval.layer2_llm_judge import _build_evidence_brief
from workflow.schema import AnalysisResult

with open("/tmp/agent_result.json") as f:
    result = AnalysisResult.model_validate(json.load(f))

l1 = run_layer1(result)
print(f"Layer 1: {'PASS' if l1.passed else 'FAIL'} ({l1.passed_checks}/{l1.total_checks})")

failed = {n: c["reason"] for n, c in l1.checks.items() if not c["passed"]}
for n, r in failed.items():
    print(f"  FAIL: {n}: {r}")

brief = _build_evidence_brief(result, l1)
with open("/tmp/evidence_brief.txt", "w") as f:
    f.write(brief)
with open("/tmp/l1_result.json", "w") as f:
    json.dump(l1.model_dump(), f, indent=2)
PYEOF
```

### 5b. Layer 2 — LLM judge agents (2 agents in parallel)

Read the evidence brief from `/tmp/evidence_brief.txt` and the rubric from
`eval/layer2_rubric.md`.

Launch **2 agents in parallel** — one with `model: sonnet`, one with `model: haiku`.

Each agent receives:
- **System prompt**: "You are an expert financial analyst serving as a judge
  evaluating a stock analysis report. The evidence has been organized into
  labeled exhibits. Be rigorous — only mark `met: true` if clearly satisfied.
  Respond ONLY with the JSON object described in the rubric."
- **User prompt**: `{evidence_brief}\n\n## Evaluation Rubric\n\n{rubric}\n\n
  Evaluate all sub-items. Respond with ONLY the JSON object.`

The expected output schema has 5 top-level keys matching `DIMENSION_SUB_ITEMS`
in `workflow/schema.py`, each containing sub-items with `{met: bool, note: str}`.

### 5c. Compute scores and assemble eval report (code)

```python
python3 << 'PYEOF'
import json, sys
sys.path.insert(0, '.')
from workflow.schema import (
    DIMENSION_SUB_ITEMS, compute_dimension_score, SubItemResult,
    JudgeDimensionScore, LLMJudgeResult, LLMJudgePoolResult,
    AggregatedDimensionScore, EvalReport, DeterministicEvalResult
)
from datetime import datetime
from pathlib import Path

DIMENSION_WEIGHTS = {
    "causal_reasoning": 0.25,
    "information_completeness": 0.25,
    "actionability": 0.20,
    "risk_awareness": 0.20,
    "user_appropriateness": 0.10,
}

sonnet_raw = { ... }  # ← Paste Sonnet judge JSON
haiku_raw  = { ... }  # ← Paste Haiku judge JSON

def compute_judge_result(raw, judge_model):
    dimension_scores = {}
    for dim_name, item_names in DIMENSION_SUB_ITEMS.items():
        dim_data = raw[dim_name]
        sub_items = {}
        met_count = 0
        for item_name in item_names:
            item_data = dim_data[item_name]
            sub_item = SubItemResult(met=item_data["met"], note=item_data["note"])
            sub_items[item_name] = sub_item
            if sub_item.met:
                met_count += 1
        score = compute_dimension_score(met_count, len(item_names))
        dimension_scores[dim_name] = JudgeDimensionScore(score=score, sub_items=sub_items)
    weighted_avg = round(sum(
        dimension_scores[d].score * w for d, w in DIMENSION_WEIGHTS.items()
    ), 2)
    dim_floor_ok = all(d.score > 2 for d in dimension_scores.values())
    passed = weighted_avg >= 4.0 and dim_floor_ok
    return LLMJudgeResult(
        causal_reasoning=dimension_scores["causal_reasoning"],
        information_completeness=dimension_scores["information_completeness"],
        actionability=dimension_scores["actionability"],
        risk_awareness=dimension_scores["risk_awareness"],
        user_appropriateness=dimension_scores["user_appropriateness"],
        overall_weighted_average=weighted_avg, passed=passed,
        judge_model=judge_model,
    )

sonnet_result = compute_judge_result(sonnet_raw, "claude-sonnet-4-6")
haiku_result  = compute_judge_result(haiku_raw,  "claude-haiku-4-5")

individual = [sonnet_result, haiku_result]
dims = {}
for d in DIMENSION_WEIGHTS:
    scores = [getattr(r, d).score for r in individual]
    dims[d] = AggregatedDimensionScore(
        mean_score=round(sum(scores)/len(scores), 2),
        min_score=min(scores), max_score=max(scores), scores=scores,
    )
overall = round(sum(dims[d].mean_score * w for d, w in DIMENSION_WEIGHTS.items()), 2)
spread = round(max(r.overall_weighted_average for r in individual)
             - min(r.overall_weighted_average for r in individual), 2)
majority = sum(1 for r in individual if r.passed) >= len(individual) / 2
floor_ok = all(dims[d].mean_score > 2.0 for d in DIMENSION_WEIGHTS)

pool = LLMJudgePoolResult(
    individual_results=individual, judge_models=[r.judge_model for r in individual],
    num_judges=2, num_succeeded=2, overall_weighted_average=overall,
    passed=overall >= 4.0 and majority and floor_ok, score_spread=spread,
    **{d: dims[d] for d in DIMENSION_WEIGHTS},
)

with open("/tmp/l1_result.json") as f:
    l1 = DeterministicEvalResult.model_validate(json.load(f))

report = EvalReport(
    ticker="TICKER", model_name="claude-opus-4-6",
    timestamp=datetime.now().isoformat(),
    layer1=l1, layer2=sonnet_result, layer2_pool=pool,
    overall_passed=l1.passed and pool.passed,
)

eval_path = Path("results") / f'TICKER_eval_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(eval_path, "w") as f:
    json.dump(report.model_dump(), f, indent=2, default=str)

print(f"Layer 1: {'PASS' if l1.passed else 'FAIL'} ({l1.passed_checks}/{l1.total_checks})")
for jr in individual:
    print(f"  {jr.judge_model}: {jr.overall_weighted_average:.2f}/5.0 {'PASS' if jr.passed else 'FAIL'}")
print(f"Pool: {pool.overall_weighted_average:.2f}/5.0 {'PASS' if pool.passed else 'FAIL'} (spread {spread})")
print(f"Overall: {'PASS' if report.overall_passed else 'FAIL'}")
print(f"Saved: {eval_path}")
PYEOF
```

---

## Architecture: How This Relates to the Normal Pipeline

```
Normal pipeline (runner.py)          Session-agent pipeline (this file)
─────────────────────────────        ─────────────────────────────────
Phase 0:  yfinance + code            Phase 0:  WebSearch + SAME code
Phase 1-3: adapter.complete_json()   Phase 1-3: Agent tool (haiku) x9
Phase 4:  adapter.complete_json()    Phase 4:  Agent tool (opus) x2
Phase 5:  _assemble_decision()       Phase 5:  SAME _assemble_decision()
L1 eval:  run_layer1()               L1 eval:  SAME run_layer1()
L2 eval:  adapter.complete_json()    L2 eval:  Agent tool (sonnet+haiku)
Scoring:  compute_dimension_score()  Scoring:  SAME compute_dimension_score()
```

The **only** difference is how LLM calls are dispatched. All schemas, prompts,
normalization, assembly, deterministic math, and eval scoring use the **exact
same source code**.
