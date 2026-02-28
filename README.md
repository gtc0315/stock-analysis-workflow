# Stock Analysis Workflow

A multi-agent stock analysis pipeline that produces actionable investment recommendations grounded in technical indicators and fundamental analysis.

LLMs handle reasoning (interpreting data, synthesizing narratives). Code handles math (prices, sizing, exits). A panel of LLM judges evaluates output quality, and an optional feedback loop iterates until quality passes.

For the design philosophy and lessons learned, see **[workflow-blueprint.md](workflow-blueprint.md)**.

## Quick Start

```bash
pip install -r requirements.txt

# Analyze CRWD with default settings (requires Ollama running locally)
python workflow/runner.py CRWD

# Full example with all options
python workflow/runner.py NVDA \
  --risk-tolerance aggressive \
  --time-horizon long \
  --position-size-usd 25000 \
  --existing-holdings "AAPL,MSFT,GOOG" \
  --max-iterations 3

# Dry-run with fixtures (no LLM or market data calls)
python workflow/runner.py CRWD --dry-run --skip-eval
```

## Architecture

```
Phase 0 (CODE)              Phase 1-3 (9 LLM workers)       Phase 4 (2 LLM)        Phase 5 (CODE)
+-------------------+       +---------------------------+    +------------------+    +------------------+
| 0a: yfinance      |       | 1a: News + sentiment      |    | 4a: Recommend    |    | Entry correction |
| 0b: RSI, MACD,    |------>| 1b: Analyst consensus      |--->|   + price levels |    | Stop snapping    |
|     SMA, Bollinger |       | 2a-2d: Fundamental (4 dim) |    | 4b: Narrative    |--->| Target assignment|
| 0c: Price zones    |       | 3a: Technical interp       |    +------------------+    | Position sizing  |
| 0d: Sector check   |       | 3b: Catalysts              |            ^               | Exit strategy    |
+-------------------+       | 3c: Risks                  |            |               +------------------+
                             +---------------------------+            |                        |
                                                                      |                        v
                             +---------------------------+            |               results/*.json
                             | Eval System               |            |
                             |  L1: 15+ deterministic    |    Feedback loop
                             |  L2: 5 LLM judges (pool)  |----(re-run Phase 4
                             +---------------------------+     with judge feedback)
```

**Design principles:**
- **Code everything deterministic** — RSI, MACD, Bollinger, support/resistance, price zones, position sizing, exits all computed in code
- **One question per LLM call** — each worker answers a single focused question with a 2-5 field schema
- **Enable parallelism** — 9 independent workers run concurrently via ThreadPoolExecutor
- **Simple schemas** — small models (7-8B) are reliable with 2-5 field outputs, unreliable with 15+
- **LLM reasons, code enforces** — LLM picks buy/sell + confidence; code computes all final numbers

## CLI Reference

| Argument | Default | Description |
|---|---|---|
| `ticker` | required | Stock ticker symbol (e.g., `CRWD`, `NVDA`, `SLV`) |
| `--risk-tolerance` | `moderate` | `conservative` / `moderate` / `aggressive` |
| `--time-horizon` | `medium` | `short` / `medium` / `long` |
| `--position-size-usd` | `10000` | Dollar budget available to invest |
| `--existing-holdings` | `""` | Comma-separated tickers already held |
| `--provider` | from config | Override LLM provider: `anthropic` / `openai` / `ollama` |
| `--dry-run` | off | Use cached fixtures, no API or market data calls |
| `--skip-eval` | off | Skip judge evaluation after analysis |
| `--max-iterations` | `1` | Feedback loop iterations (`1` = single pass, `3` = up to 2 revisions) |

## How LLM Reasoning Feeds Into Code Math

The LLM doesn't just produce text — its reasoning directly affects the numerical output:

### Confidence → Position Sizing

High conviction = bigger bet, low conviction = smaller bet. Risk tolerance sets the ceiling, confidence scales within it.

```
Position = budget × risk_ceiling × confidence

Examples ($10k budget, moderate risk → 75% ceiling):
  90% confidence  →  $10k × 75% × 90%  =  $6,750
  70% confidence  →  $10k × 75% × 70%  =  $5,250
  45% confidence  →  $10k × 75% × 45%  =  $3,375
```

### Fundamental Rating → Target Selection

Strong fundamentals shift the base target toward the optimistic end of the technical zone. Weak fundamentals shift toward conservative (take profits earlier).

```
Base target = conservative + blend% × (optimistic - conservative)

  strong fundamentals:  blend = 67%  →  lean optimistic
  moderate:             blend = 50%  →  midpoint
  weak:                 blend = 33%  →  lean conservative
```

### What LLM Controls vs What Code Controls

| LLM decides | Code enforces |
|---|---|
| buy / hold / sell / avoid | Position size (risk tolerance × confidence) |
| Confidence score (0.0-1.0) | Entry price (current price ±1% for short horizon) |
| Fundamental rating | Stop loss (snapped to nearest technical support) |
| Narrative, bull/bear case | Targets (assigned from Bollinger/MA/pivot zones, shifted by fundamentals) |
| | Exit strategy tiers, R:R math, hard caps |

## Time Horizon Effects

| | Short | Medium | Long |
|---|---|---|---|
| **Entry** | Current price (±1%) — "buy NOW?" | Small pullback OK (±3%) | Wait for better price (±5%, MA-anchored) |
| **Exit strategy** | 1 tier: full exit at base target | 2 tiers: lock half early, close at base | 3 tiers: lock 1/3, scale out, let rest ride |
| **Target cap** | 1.5× current price | 2.0× | 3.0× |

## Price Zones

All prices are grounded in technical indicators, not LLM-hallucinated:

- **Stop zone**: Pivot supports, Bollinger lower band, SMA-50/200 below current price
- **Entry zone**: Tight range around current price, width varies by time horizon
- **Target zone**: Pivot resistances, Bollinger upper band, SMA-50/200 above current price

The LLM sees these zones in its prompt and must pick from them. Phase 5 then reassigns targets directly from zone levels regardless of what the LLM picked.

## Eval System

### Layer 1: Deterministic (15+ checks)

Hard-coded rule checks on every output:
- **Format**: required fields present and correctly typed
- **Math**: R:R ratio matches formula, position sizing percentage correct
- **Price ordering**: stop < entry < conservative < base < optimistic
- **Bounds**: confidence 0-1, targets within horizon cap, entry near current price
- **Risk alignment**: conservative → smaller positions and tighter stops
- **Exit strategy**: correct tier count, ascending prices, proper stop-trailing
- **Concentration**: flags sector over-concentration with existing holdings

### Layer 2: LLM Judge Pool (5 models, 25 sub-items)

Five independent judge models each evaluate 25 boolean sub-items across 5 dimensions:

| Dimension | Weight | Key sub-items |
|---|---|---|
| Causal Reasoning | 25% | Metrics cited, technical alignment, confidence calibrated, counterarguments |
| Information Completeness | 25% | News substantive, earnings discussed, catalyst/risk variety, bull/bear balanced |
| Actionability | 20% | Entry justified, targets realistic, stop loss grounded, conditions measurable |
| Risk Awareness | 20% | Diverse risk categories, bear case detailed, portfolio impact, downside quantified |
| User Appropriateness | 10% | Position size fits profile, time horizon matched, tone appropriate |

**Scoring**: Dimension scores computed deterministically from sub-item pass rate: `score = max(1, round(1 + 4 × (met/total)))`.

**Pass criteria**: Weighted average ≥ 4.0/5.0 AND majority of judges individually pass AND no dimension mean ≤ 2.0.

### Layer 3: Human Eval (manual)

Template at `eval/layer3_human/template.md` with gold-standard examples in `eval/layer3_human/examples/`. Use to calibrate the LLM judges.

## Feedback Loop

When `--max-iterations > 1`, the system runs a critique-and-revise loop:

1. Run full pipeline (11 LLM calls) → evaluate with 5 judges
2. Collect failures, **prioritize by dimension weight × judge consensus**
3. **Cap to top 6** actionable items — prevents small-model overwhelm
4. **Exclude data gaps** (missing news/catalysts) — can't fix by re-running Phase 4
5. **Include "keep what works"** list — prevents regression on passing items
6. Re-run Phase 4 only (2 LLM calls) with feedback injected into prompts
7. Even if an iteration passes, **keep going** — might score higher next round
8. **Track best result** across all iterations — always return the highest-scoring one
9. **Early stop on regression** — if score drops >0.05, revert to best and stop

```
Example: --max-iterations 3
  Iteration 0: 3.80/5.0 FAILED — 16 failures
  Iteration 1: 4.10/5.0 PASSED — 8 failures   ↑+0.30  ★ selected
  Iteration 2: 3.95/5.0 PASSED — 10 failures  ↓-0.15  (regression, stopped)
  Best: iteration 1 (4.10/5.0) — 4 extra LLM calls
```

## Configuration

Edit `config.yaml`:

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    default_model: claude-sonnet-4-5-20250929
  openai:
    api_key_env: OPENAI_API_KEY
    default_model: gpt-4o
  ollama:
    base_url: http://localhost:11434
    default_model: llama3.1:8b

workflow:
  provider: ollama        # active provider for analysis
  parallel: true          # run workers concurrently
  max_workers: 4          # max concurrent LLM calls

eval:
  judge_provider: ollama  # must differ from workflow provider
  judge_models:           # pool of judges (run in parallel)
    - llama3.1:8b
    - qwen3:8b
    - granite3.2:8b
    - deepseek-r1:8b
    - gemma2:9b
```

### Provider Setup

**Ollama** (local, free): Install from [ollama.com](https://ollama.com), then pull models:
```bash
ollama pull llama3.1:8b
ollama pull qwen3:8b        # for judge pool
ollama pull granite3.2:8b   # for judge pool
```

**Anthropic**: Set `ANTHROPIC_API_KEY` env var. Default model: `claude-sonnet-4-5-20250929`.

**OpenAI**: Set `OPENAI_API_KEY` env var. Default model: `gpt-4o`.

## LLM Call Budget

| Phase | Calls | Notes |
|---|---|---|
| Phase 1-3: Workers | 9 | Parallel (4 concurrent) |
| Phase 4: Recommendation + Narrative | 2 | Sequential (4b depends on 4a) |
| **Total per run** | **11** | |
| Feedback iteration | +2 | Re-runs Phase 4 only |
| Eval (judge pool) | +5 | 5 judge models in parallel |

## Cross-Model Comparison

```bash
python compare/cross_model_compare.py CRWD \
  --providers ollama,anthropic,openai \
  --risk-tolerance moderate \
  --time-horizon medium
```

Runs the same ticker across providers and compares eval scores head-to-head.

## Adding a New LLM Adapter

1. Create `adapters/your_adapter.py` implementing `LLMAdapter`:

```python
from .base import LLMAdapter

class YourAdapter(LLMAdapter):
    def complete(self, system_prompt, user_prompt, temperature=0.3, max_tokens=4000):
        ...  # Return text response

    def complete_json(self, system_prompt, user_prompt, schema, temperature=0.1, max_tokens=4000):
        ...  # Return parsed JSON dict

    def get_model_name(self):
        return self.model
```

2. Add provider config to `config.yaml`
3. Register in `workflow/runner.py:create_adapter()`

## Project Structure

```
stock-analysis-workflow/
├── config.yaml                        # Provider + workflow + eval config
├── requirements.txt                   # Python dependencies
├── workflow-blueprint.md              # Design philosophy & lessons learned
│
├── workflow/
│   ├── runner.py                      # Main orchestrator (pipeline, feedback loop, CLI)
│   ├── schema.py                      # Pydantic models + scoring formula
│   ├── indicators.py                  # RSI, MACD, SMA, Bollinger bands (pure math)
│   ├── concentration.py               # Sector concentration detection
│   └── prompts/                       # 11 prompt templates
│       ├── system.md                  # Shared system prompt (5 principles)
│       ├── worker_1a_news.md          # → recent news headlines
│       ├── worker_1b_analyst.md       # → analyst consensus
│       ├── worker_2a_valuation.md     # → valuation assessment
│       ├── worker_2b_growth.md        # → growth trajectory
│       ├── worker_2c_moat.md          # → competitive moat
│       ├── worker_2d_balance.md       # → balance sheet health
│       ├── worker_3a_technical.md     # → interpret pre-computed indicators
│       ├── worker_3b_catalysts.md     # → upcoming catalysts
│       ├── worker_3c_risks.md         # → key risks
│       ├── step5a_recommendation.md   # → buy/sell + price levels
│       └── step5b_narrative.md        # → conditions, bull/bear case
│
├── adapters/
│   ├── base.py                        # Abstract LLMAdapter interface
│   ├── anthropic_adapter.py           # Claude (claude-sonnet-4-5-20250929)
│   ├── openai_adapter.py              # GPT (gpt-4o)
│   └── ollama_adapter.py              # Local Ollama (600s timeout, retry on timeout)
│
├── eval/
│   ├── run_eval.py                    # Eval orchestrator (L1 + L2)
│   ├── layer1_deterministic.py        # 15+ hard-coded rule checks
│   ├── layer2_llm_judge.py            # LLM-as-judge, 5 models × 25 sub-items
│   ├── layer2_rubric.md               # Scoring rubric (5 dimensions, 25 items)
│   ├── report.py                      # Human-readable report generator
│   └── layer3_human/                  # Manual grading template + gold examples
│
├── compare/
│   └── cross_model_compare.py         # Same ticker across providers, compare scores
│
├── tests/fixtures/                    # CRWD mock data for --dry-run
└── results/                           # Auto-saved JSON outputs + .eval.json reports
```

## Disclaimer

This is an analytical tool, not financial advice. All outputs should be treated as one input into a broader decision-making process.
