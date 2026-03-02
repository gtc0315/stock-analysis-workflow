# Stock Analysis Workflow

**A self-improving multi-agent pipeline that produces investment recommendations using local 8B-parameter LLMs.**

Built from an original observation: small LLMs are unreliable at complex tasks but reliable at simple ones — the same principle that makes GPUs outperform CPUs. Decompose one hard prompt into many trivial workers, and reliability emerges from the architecture, not the model.

This project explores **agentic workflow design**, **LLM-as-judge evaluation**, and **self-correcting feedback loops** — all running locally on consumer hardware via Ollama, with zero API costs.

For the design philosophy and lessons learned, see **[workflow-blueprint.md](workflow-blueprint.md)**.

---

## Key Ideas

### 1. Swarm Architecture (GPU-Style Decomposition)

Instead of asking one LLM call to produce a 15-field analysis (which fails ~40% of the time on 8B models), the pipeline decomposes the task into **9 parallel workers**, each answering exactly one question with a 2-5 field schema (~95% success rate). Independent workers run concurrently via ThreadPoolExecutor, then deterministic code assembles the final output — the LLM never does math or data passthrough.

### 2. Three-Layer Eval with Multi-Judge Pool

A three-tier evaluation system scores every output automatically:
- **Layer 1**: 15+ deterministic rule checks (math correctness, price ordering, bounds)
- **Layer 2**: 5 independent LLM judge models evaluate 25 boolean sub-items across 5 weighted dimensions, with self-evaluation exclusion (a model never judges its own output)
- **Layer 3**: Human eval template for calibrating the automated judges

### 3. Two-Tier Self-Correcting Feedback Loop

When eval fails, the system doesn't just retry — it **diagnoses which workers produced weak output** by mapping judge sub-item failures back to responsible workers, then selectively re-runs only those workers before re-running the synthesis phase. Feedback is prioritized by dimension weight multiplied by judge consensus, capped to the top 6 items. A "keep what works" list prevents regression, and early-stop detects score deterioration.

### 4. Judge-as-Worker Swap (Capability Escalation)

When the feedback loop exhausts all iterations and the worker model still can't pass eval, the system automatically **promotes the strictest judge** (lowest-scoring) to act as the Phase 4 worker. The insight: the judge that scores lowest knows most precisely what "good" looks like. The swapped model is auto-excluded from the judge pool via existing self-eval filters, so evaluation integrity is preserved.

```
Normal feedback loop (--max-iterations) exhausted
  ↓
Find strictest judge (lowest overall_weighted_average)
  ↓
Re-run Phase 4 with judge model as worker (4 LLM calls)
  ↓
Evaluate (swapped model auto-excluded from judging)
  ↓
Repeat up to --max-worker-swap times
```

### 5. Pre-Computed Fact Injection for Small Models

Rather than expecting 8B models to perform multi-step reasoning (look up stop price → find matching indicator → name it → compute percentage), the pipeline **pre-computes deterministic facts** and injects them directly into prompts. The model's job becomes citing and contextualizing, not computing — reducing the inference burden by ~80%.

### 6. Evidence-Based Judge Prompting

LLM judges receive a structured **evidence brief** that pre-assembles exhibits for each evaluation criterion. This shifts the judge's task from "search a 2000-token analysis for evidence" to "verify whether this pre-extracted evidence satisfies the criterion" — making 8B judges as reliable as larger models.

---

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

## Quick Start

```bash
pip install -r requirements.txt

# Analyze CRWD with default settings (requires Ollama running locally)
python workflow/runner.py CRWD

# Full example with feedback loop
python workflow/runner.py NVDA \
  --risk-tolerance aggressive \
  --time-horizon long \
  --position-size-usd 25000 \
  --existing-holdings "AAPL,MSFT,GOOG" \
  --max-iterations 3

# With judge-as-worker swap (when 8B can't pass eval)
python workflow/runner.py SLV \
  --max-iterations 3 \
  --max-worker-swap 2

# Dry-run with fixtures (no LLM or market data calls)
python workflow/runner.py CRWD --dry-run --skip-eval
```

## Example Output

Running `python workflow/runner.py RACE --risk-tolerance aggressive --time-horizon short --position-size-usd 20000 --max-iterations 3` produces:

### Terminal Summary
```
================================================================
  ANALYSIS COMPLETE: RACE  (llama3.1:8b)
================================================================

  -- Phase 0: Deterministic Data ──────────────────────────────
  Price: $379.92  |  RSI: 60.1 (neutral)  |  MACD: bullish
  Trend: uptrend  |  Concentration risk: no
  Supports:    $370.00, $360.00, $340.78
  Resistances: $390.00, $393.50, $400.00
  Bollinger:   $355.40 – $405.20 (bandwidth: 0.12)
  Target zone: $390.00 (Pivot R1), $393.50 (SMA-50), $400.00 (Round), $405.20 (BB upper)
  Stop zone:   $370.00 (Pivot S1), $360.00 (Pivot S2), $355.40 (BB lower)

  -- Phase 1-3: Parallel Workers ──────────────────────────────
  Worker                Tok In  Tok Out   Latency
  ──────────────────── ─────── ──────── ─────────
  1a_news                  480      120     12.3s
  1b_analyst               350       85      9.8s
  2a_valuation             290       95      8.1s
  2b_growth                310      110      9.5s
  2c_moat                  280       90      7.9s
  2d_balance               320      105      8.7s
  3a_technical             450      130     11.2s
  3b_catalysts             380      140     10.4s
  3c_risks                 360      125     10.1s

  -- Phase 4: Sequential Workers ──────────────────────────────
  4a_recommendation       1,850      280     22.5s
  4b_bull                   920       95     11.3s
  4b_bear                   940      110     12.1s
  4b_conditions             880      120     11.8s

  Total: 13 LLM calls, 7,810 tokens in, 1,505 tokens out

  -- Analysis Summary ─────────────────────────────────────────
  Fundamental: moderate  |  Technical: bullish
  Workers: 9 succeeded, 0 failed

  -- Decision ─────────────────────────────────────────────────
  Recommendation: BUY (80% confidence)
  Entry: $379.92  |  Target: $410.14  |  Stop: $370.00
  Risk/Reward: 3.0x  |  Position: $15,000 (75%)

  -- Exit Strategy ────────────────────────────────────────────  (short horizon)
  $  370.00  STOP    sell 100%
             Hard stop — full exit
  $  410.14  PROFIT  sell 100%
             Full exit at base target — short horizon, take what you can

  Buy RACE with a target of $410 and stop at $370, expecting
  growth from new hybrid sports car launch.

  -- Eval Results ─────────────────────────────────────────────
  L1 Deterministic: 18/18 PASSED
  L2 Judge Pool:    4.20/5.0 PASSED
    Judges: 5/5 succeeded  |  Spread: 0.40
    Causal Reasoning          4.2/5  [4-5]
    Information Completeness  4.0/5  [3-5]
    Actionability             4.4/5  [4-5]
    Risk Awareness            4.0/5  [3-5]
    User Appropriateness      4.6/5  [4-5]

================================================================
```

### JSON Output (saved to `results/`)

The full structured output is saved as JSON for programmatic use:

```json
{
  "ticker": "RACE",
  "model_name": "llama3.1:8b",
  "risk_profile": {
    "risk_tolerance": "aggressive",
    "time_horizon": "short",
    "position_size_usd": 20000.0,
    "existing_holdings": ["AAPL", "NVDA", "TSLA", "IAU"]
  },
  "step5_decision": {
    "recommendation": "buy",
    "confidence": 0.8,
    "entry_price": {
      "ideal": 379.92,
      "acceptable_range": [376.12, 383.72]
    },
    "target_price": {
      "conservative": 390.00,
      "base": 410.14,
      "optimistic": 430.28
    },
    "stop_loss": 370.00,
    "position_size_recommended_usd": 15000.00,
    "risk_reward_ratio": 3.05,
    "exit_strategy": [
      {"price": 370.00, "action": "stop_loss", "sell_pct": 100, "note": "Hard stop — full exit"},
      {"price": 410.14, "action": "take_profit", "sell_pct": 100, "note": "Full exit at base target"}
    ],
    "bull_case_summary": "Ferrari's hybrid sports car launch in Q2 2025 is expected to drive significant sales growth...",
    "bear_case_summary": "If global supply chains are disrupted, RACE could see a 10% decline to $370 or lower...",
    "one_line_summary": "Buy RACE with a target of $410 and stop at $370."
  }
}
```

A separate `.eval.json` file contains the full evaluation report with per-judge scores and sub-item breakdowns.

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
| `--max-worker-swap` | `0` | After feedback fails, promote strictest judge as worker for N extra attempts |

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

When `--max-iterations > 1`, the system runs a two-tier critique-and-revise loop:

1. Run full pipeline (13 LLM calls) → evaluate with 5 judges
2. Collect failures, split into **worker-level** and **Phase 4-level** feedback
3. **Worker re-runs**: if judges flag data-quality issues (vague metrics, limited risks, etc.), re-run the responsible Phase 1-3 workers with targeted feedback
4. **Phase 4 re-runs**: re-run recommendation + narrative with updated data + Phase 4 feedback
5. Feedback is **prioritized by dimension weight × judge consensus**, **capped to top 6** items
6. **"Keep what works"** list prevents regression on passing items
7. Even if an iteration passes, **keep going** — might score higher next round
8. **Track best result** across all iterations — always return the highest-scoring one
9. **Early stop on regression** — if score drops >0.05, revert to best and stop

### Worker-Level Feedback

Judge sub-items are mapped to responsible workers:

| Sub-item | Worker(s) | What it fixes |
|---|---|---|
| `metrics_cited` | 2a-2d (fundamentals) | "P/E of 28" instead of "fairly valued" |
| `news_substantive` | 1a (news) | More specific, impactful headlines |
| `catalyst_variety` | 3b (catalysts) | More diverse catalyst types |
| `risk_variety`, `diverse_risk_categories` | 3c (risks) | Market + regulatory + competitive risks |

```
Example: --max-iterations 3
  Iteration 0: 3.80/5.0 FAILED — 16 failures
  → Re-running 5 workers (2a,2b,2c,2d,3c) + Phase 4
  Iteration 1: 4.10/5.0 PASSED — 8 failures   ↑+0.30  ★ selected
  Iteration 2: 3.95/5.0 PASSED — 10 failures  ↓-0.15  (regression, stopped)
  Best: iteration 1 (4.10/5.0) — 12 extra LLM calls (4 Phase 4 + 8 worker)
```

### Judge-as-Worker Swap

When `--max-worker-swap > 0` and the feedback loop exhausts without passing, the system escalates by promoting the strictest judge to act as the Phase 4 worker:

1. Find the judge with the lowest `overall_weighted_average` — this judge is the hardest to satisfy, so it knows best what quality looks like
2. Create an adapter for that judge model
3. Re-run Phase 4 (recommendation + 3 narrative calls = 4 LLM calls) using the judge model
4. Evaluate the result — the swapped model is automatically excluded from the judge pool (self-eval filter), so remaining judges evaluate impartially
5. Repeat up to `--max-worker-swap` times with feedback between iterations

```
Example: --max-iterations 3 --max-worker-swap 2
  Iteration 0: 3.75/5.0 FAILED
  Iteration 1: 3.90/5.0 FAILED  (feedback loop exhausted)
  Iteration 2: 3.85/5.0 FAILED  (regression, stopped)
  → Swapping: strictest judge (gemma2:9b, scored 3.60) becomes worker
  Swap-1 [gemma2:9b]: 4.15/5.0 PASSED  ★ selected
```

### 8B Model Optimizations

The pipeline is designed for small (8B parameter) local models via Ollama:

1. **Split narratives**: Step 5b is 3 separate calls (bull, bear, conditions) with 1-2 output fields each, instead of 1 call with 4 fields
2. **Pre-computed facts**: `_compute_phase4b_facts()` computes stop-loss technical basis, downside %, dollar loss, analyst consensus interpretation, and injects them into prompts so the 8B model can cite them directly
3. **Concrete examples**: Worker prompts include good/bad JSON examples showing the expected specificity level
4. **Auto-pass for ETFs**: `earnings_discussed` judge sub-item auto-passes when `next_earnings_date` is null (ETFs like SLV have no earnings)
5. **One question per call**: Each worker handles exactly one assessment (1-4 output fields), keeping within 8B model capabilities

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
| Phase 4a: Recommendation | 1 | Sequential (4b depends on 4a output) |
| Phase 4b: Narratives (split) | 3 | Bull case + bear case + conditions/summary |
| **Total per run** | **13** | |
| Feedback iteration (Phase 4 only) | +4 | Re-runs recommendation + 3 narrative calls |
| Feedback iteration (with workers) | +4 to +9 | Re-runs failing workers + Phase 4 |
| Judge swap iteration | +4 | Phase 4 only (workers unchanged) |
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
│   └── prompts/                       # 14 prompt templates
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
│       ├── step5b_narrative.md        # Legacy combined (kept for backward compat)
│       ├── step5b_bull.md             # → bull case (1 field, pre-computed facts)
│       ├── step5b_bear.md             # → bear case (1 field, pre-computed downside)
│       └── step5b_conditions.md       # → conditions + one-liner (2 fields)
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

## Design Decisions & Trade-offs

Documenting the reasoning behind non-obvious architectural choices:

| Decision | Why | Trade-off |
|---|---|---|
| 9 parallel workers instead of 3 complex calls | 8B models produce ~95% valid output at 2-5 fields, ~60% at 15+ fields | More LLM calls, but each is fast and reliable |
| Deterministic assembly (Phase 5) instead of LLM math | Small models get R:R ratios wrong ~30% of the time | Code can't reason about edge cases, but math is always correct |
| 5-model judge pool instead of 1 judge | Single judge introduces scoring bias; pool reduces variance | 5x eval cost, but score spread reveals ambiguous analyses |
| Self-eval exclusion filter | A model scoring its own output inflates scores | Reduces judge pool by 1 when worker model is in the pool |
| Pre-computed fact injection instead of chain-of-thought | 8B models fail multi-step reasoning (look up → compute → cite) | Shifts inference burden from model to code; model just cites |
| Judge-as-worker swap instead of larger model fallback | The strictest judge already knows the rubric intimately | Burns a judge from the pool (4 remaining), but passes more often |
| Evidence briefs for judges | 8B judges can't reliably search 2000-token analyses | Pre-assembles exhibits per criterion; ~80% less judge inference |
| Worker-level feedback routing | Re-running all 9 workers wastes calls; targeted re-runs are 2-5x cheaper | Requires maintaining a sub-item → worker mapping table |

## Bigger Picture: Agentware

### The Problem

Today, people interact with LLMs ad-hoc. Every prompt is improvised, every workflow lives in someone's head, quality is inconsistent, and nothing is reusable. When you switch from Claude to GPT, you start over. When a colleague wants your process, you can't hand it to them in a runnable form.

This is the equivalent of the software industry before version control, package managers, and testing frameworks — everyone writing one-off scripts with no structure, no quality assurance, and no way to build on each other's work.

### The Concept

**Agentware** is a standardized layer between the user and the LLM:

```
User → Agentware (workflows + eval) → Any LLM → Output
```

It is NOT a product or an app. It is a **layer** — like how software is a layer between humans and hardware. The key properties:

- **Workflows are portable.** A workflow written once runs on Claude, GPT, Gemini, Llama, or any future model. Switching models is a config change, not a rewrite.
- **Knowledge is encoded, not improvised.** Domain experts (investors, doctors, lawyers, engineers) capture their expertise as structured, repeatable workflows — not as prompts they type from memory each time.
- **Quality is measurable.** Every workflow output is automatically evaluated. You know whether the result is trustworthy before you act on it.

The key distinction from traditional software: software is **deterministic** (human writes exact rules, computer follows them). Agentware is **directive** (human sets goals and quality standards, AI decides how to execute). This makes it capable of handling complex, judgment-heavy tasks that traditional software cannot.

### Why Eval is the First Priority

Standards and protocols matter, but they emerge from practice, not committees. The agentware ecosystem's most urgent gap is **eval** — the ability to measure whether an AI-driven workflow actually produces good output.

Without eval:
- You can't compare workflows (is mine better than yours?)
- You can't compare models (does it matter if I use Claude vs GPT?)
- You can't improve over time (what should I change to get better results?)
- You can't trust the output (is this analysis reliable enough to act on?)

With eval, standards emerge naturally — the moment you evaluate two workflows side by side, you need shared input/output formats, quality dimensions, and scoring rubrics. Eval forces standardization from the bottom up.

This is why this project implements a **three-layer eval architecture** — deterministic checks catch format and math errors, LLM judges evaluate reasoning quality, and human eval periodically calibrates the automated judges. Over time, insights from Layer 3 sink into Layer 2 (better rubrics), and from Layer 2 into Layer 1 (new deterministic rules). The system gets cheaper and faster while quality improves.

### The Hypothesis

If you run the same workflow across multiple LLMs and the eval scores are similar, it suggests that **the workflow matters more than the model**. This has implications:

- LLMs commoditize — value shifts from model providers to workflow creators
- Domain expertise becomes the scarce asset, not compute or model architecture
- The agentware layer (workflows + eval standards) becomes the durable, accumulating source of value

This project is a first concrete test of that hypothesis, using stock analysis as the domain.

### What This Project Demonstrates

A reference implementation — the first open-source workflow that ships with built-in eval:

1. How to structure an LLM-agnostic workflow with strict input/output schemas
2. How to implement three-layer eval for a real domain
3. How to compare model performance on identical tasks with identical quality criteria
4. How self-correcting feedback loops make unreliable models produce reliable output

It is intentionally scoped to one domain (investment analysis) to stay concrete. But the architecture — workflow runner, adapter interface, eval layers, cross-model comparison — is designed as a template that others can fork for their own domains.

### Long-Term Ecosystem Vision

If this pattern proves useful, the natural next steps are:

- **Workflow Registry** — a public repository where domain experts contribute evaluated workflows (like npm for agent workflows)
- **Universal Eval Standard** — a shared format for eval rubrics and scoring so workflows across domains can be compared and composed
- **Community-contributed eval rubrics** — domain experts define "what good looks like" for their field, which is arguably more valuable than the workflows themselves

The full vision is documented in **[VISION-agentware-eval-framework.md](VISION-agentware-eval-framework.md)**.

## Disclaimer

This is an analytical tool, not financial advice. All outputs should be treated as one input into a broader decision-making process.

---

## Author

**Tianchang Gu** — [GitHub](https://github.com/gtc0315) · [gtianchang@gmail.com](mailto:gtianchang@gmail.com)

Building toward LLM-agnostic agentic systems — where the architecture, not the model, is the product. Interested in the intersection of practical systems engineering and frontier AI capabilities.

Open to connecting: if this work resonates with what you're building, feel free to reach out.

## License

Copyright 2026 Tianchang Gu. All rights reserved.

This repository is shared for **portfolio and educational purposes**. You may read, study, and reference the ideas and architecture. Forking, copying, or using substantial portions of the code in commercial or production systems requires explicit written permission from the author.
