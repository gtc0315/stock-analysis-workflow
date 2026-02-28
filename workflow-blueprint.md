# Workflow Blueprint: Swarm Architecture for LLM Pipelines

A reference guide for designing LLM workflows that maximize reliability with small, local models. Built from the stock analysis workflow experiment comparing "many small workers" (GPU-style) vs "few complex calls" (CPU-style).

---

## Table of Contents

1. [Core Thesis](#core-thesis)
2. [Design Principles](#design-principles)
3. [Architecture Pattern](#architecture-pattern)
4. [Pipeline Phases](#pipeline-phases)
5. [Worker Design Patterns](#worker-design-patterns)
6. [Output Normalization](#output-normalization)
7. [Parallelism & Thread Safety](#parallelism--thread-safety)
8. [Eval System](#eval-system)
9. [Lessons Learned](#lessons-learned)
10. [Metrics: Before vs After](#metrics-before-vs-after)
11. [Applying This to Other Workflows](#applying-this-to-other-workflows)
12. [File Reference](#file-reference)

---

## Core Thesis

**Small LLMs (7-8B parameters) are unreliable at complex, multi-field tasks but reliable at simple, focused ones.** By decomposing a pipeline into many tiny workers — each answering exactly one question with a 2-5 field schema — you can build reliable systems from unreliable components.

The analogy: GPUs beat CPUs not because each core is powerful, but because the workload is decomposed into thousands of simple, parallel operations. The same applies to LLM workflows.

---

## Design Principles

These four rules drove every design decision:

### 1. Code Everything Deterministic

**Never ask an LLM to copy data or do math.** If the answer can be computed, compute it.

| Task | Before (LLM) | After (Code) |
|------|--------------|--------------|
| RSI, MACD, SMA | LLM hallucinated values | `indicators.py` computes from price history |
| Risk/reward ratio | LLM guessed math wrong | `_assemble_decision()` computes `(target - entry) / (entry - stop)` |
| Position size % | LLM sometimes exceeded 100% | Code clamps to risk tolerance limits |
| Sector concentration | LLM missed it ~40% of the time | `concentration.py` checks yfinance sector data |
| Price ordering | LLM violated stop < entry < target | Code enforces ordering in Phase 5 |
| Data gathering | LLM copied 75% of yfinance data | `_build_data_gathering_base()` maps directly |

**Key insight:** Every time a small LLM does math or data passthrough, it introduces error. Move those tasks to code and the LLM only does what LLMs are good at: reasoning about language.

### 2. One Question Per LLM Call

Each worker answers exactly one focused question. The prompt says what the question is, provides only the data needed to answer it, and specifies the exact output format.

**Bad** (old pipeline — Step 2 prompt):
> "Analyze the valuation, growth trajectory, competitive moat, and balance sheet health. For each dimension provide an assessment and evidence list. Also determine an overall fundamental rating."
> Schema: 5 nested objects, 15+ fields

**Good** (new Worker 2a prompt):
> "Is CRWD cheap, fair, or expensive relative to its sector peers?"
> Schema: `{ assessment: str, evidence: [str] }`

The small model gets Worker 2a right almost every time. It frequently fumbled the 15-field version.

### 3. Enable Parallelism

Independent workers run concurrently via `ThreadPoolExecutor`. This doesn't help with single-GPU Ollama (requests queue), but dramatically speeds up API-based providers where calls can truly run in parallel.

**Architectural rule:** If Worker A's output doesn't feed into Worker B's input, they should run in parallel.

### 4. Simple Schemas

Each worker output has 2-5 fields maximum. Pydantic validates everything. The smaller the schema, the higher the probability the model produces valid output on the first attempt.

| Schema | Fields | First-attempt success rate (llama3.1:8b) |
|--------|--------|------------------------------------------|
| `DimensionWorkerOutput` | 2 (assessment, evidence) | ~95% |
| `TechInterpretationOutput` | 3 (trend, rating, volume) | ~90% |
| `RecommendationOutput` | 7 (prices, recommendation) | ~85% |
| Old `FundamentalAnalysisOutput` | 15+ (4 nested objects) | ~60% |

---

## Architecture Pattern

```
Phase 0 (CODE, ~0.1s)          Phase 1-3 (9 LLM workers, PARALLEL)          Phase 4 (2 LLM, SEQUENTIAL)     Phase 5 (CODE)
+-----------------+             +----------------------------------+          +---------------------+          +----------+
| 0a: yfinance    |             | 1a: News headlines + sentiment   |          | 4a: Recommendation  |          | Assemble |
| 0b: RSI/MACD/SMA|----------->| 1b: Analyst consensus            |--------->|     + price levels   |--------->| + math   |
| 0c: Sector check|             | 2a: Valuation assessment         |          | 4b: Narratives      |          | + clamp  |
+-----------------+             | 2b: Growth assessment            |          +---------------------+          +----------+
                                | 2c: Moat assessment              |
                                | 2d: Balance sheet assessment     |
                                | 3a: Technical interpretation     |
                                | 3b: Catalyst identification      |
                                | 3c: Risk identification          |
                                +----------------------------------+
```

**The pipeline has 5 phases with 3 dependency boundaries:**
1. Phase 0 must complete before Phases 1-3 (workers need the data)
2. Phases 1-3 must complete before Phase 4 (recommendation needs all analysis)
3. Phase 4a must complete before 4b (narratives reference the recommendation)

**Sequential LLM depth: 3** (parallel batch -> 4a -> 4b), down from 6 in the old pipeline.

---

## Pipeline Phases

### Phase 0: Deterministic Data Gathering (Code)

Three sub-phases, all in code:

**0a: Parse yfinance** (`_build_data_gathering_base()`)
- Fetches `yf.Ticker(symbol).info` and `stock.history(period="1y")`
- Maps directly to `DataGatheringOutput` fields (price, PE, PS, market cap, etc.)
- Leaves `recent_news=[]` and `analyst_consensus=None` as placeholders for LLM workers

**0b: Technical Indicators** (`indicators.py`)
- RSI (Wilder's, 14-period) from price history
- MACD (12/26/9 standard) with direction classification
- SMA-50 and SMA-200 with price relationship and golden cross detection
- Volume statistics (5d/30d ratio, conviction assessment)
- Support/resistance levels from pivot points and round numbers
- Trend classification from SMA relationships

**0c: Sector Concentration** (`concentration.py`)
- Fetches sector for each holding via yfinance (with `@lru_cache`)
- Flags concentration if >=50% of holdings share the same sector
- Generates human-readable description for the analysis report

### Phase 1-3: Parallel LLM Workers

9 workers run via `ThreadPoolExecutor(max_workers=4)`:

| Worker | Question | Schema | Fields |
|--------|----------|--------|--------|
| 1a News | "List 3-5 recent news headlines with sentiment" | `NewsWorkerOutput` | 1 (headlines list) |
| 1b Analyst | "Estimate analyst consensus: buy/hold/sell + target" | `AnalystWorkerOutput` | 4 |
| 2a Valuation | "Is this stock cheap, fair, or expensive?" | `DimensionWorkerOutput` | 2 |
| 2b Growth | "Is growth accelerating, stable, or decelerating?" | `DimensionWorkerOutput` | 2 |
| 2c Moat | "Does this company have a strong competitive moat?" | `DimensionWorkerOutput` | 2 |
| 2d Balance | "Is the balance sheet healthy?" | `DimensionWorkerOutput` | 2 |
| 3a Technical | "Is the technical picture bullish/neutral/bearish?" | `TechInterpretationOutput` | 3 |
| 3b Catalysts | "List 3 upcoming positive catalysts" | `CatalystWorkerOutput` | 1 (catalysts list) |
| 3c Risks | "List 3 key risks" | `RiskWorkerOutput` | 1 (risks list) |

**Workers 2a-2d share the same schema** (`DimensionWorkerOutput`), making normalization reusable.

After all workers complete, assembly functions merge results into the standard step-level schemas that the eval system expects:
- `_assemble_step1()` — merges base data + Worker 1a/1b
- `_assemble_step2()` — merges Workers 2a-2d + deterministic rating
- `_assemble_step3()` — merges Phase 0b indicators + Worker 3a interpretation
- `_assemble_step4()` — merges Workers 3b/3c + Phase 0c concentration

### Phase 4: Sequential LLM Workers

Two workers that must run sequentially (4b needs 4a's output):

**Worker 4a: Recommendation** (`RecommendationOutput`, 7 fields)
- Receives: compact summaries from all previous phases
- Outputs: buy/hold/sell, confidence, entry/target/stop prices, position size

**Worker 4b: Narratives** (`NarrativeOutput`, 4 fields)
- Receives: 4a's recommendation + analysis summaries
- Outputs: key conditions, bull case, bear case, one-line summary

**Why are these sequential?** The narrative must reference the specific recommendation. Asking the LLM to generate both simultaneously produces inconsistent outputs (e.g., "buy" recommendation but bearish narrative).

### Phase 5: Deterministic Assembly (Code)

`_assemble_decision()` computes all derived fields:
- **Risk/reward ratio** = (target_base - entry) / (entry - stop_loss)
- **Position size %** = recommended_usd / input_usd
- **Position clamping** per risk tolerance (conservative <=50%, moderate <=75%, aggressive <=100%)
- **Price ordering enforcement** — ensures stop < entry < conservative target < base target
- **Fundamental rating** — keyword-based heuristic scanning dimension assessments

---

## Worker Design Patterns

### Prompt Template Pattern

Every worker prompt follows this structure:

```markdown
# Worker [ID]: [Title]

[One clear question in bold]

## Data

- Field 1: {{placeholder1}}
- Field 2: {{placeholder2}}

## Output

Respond with ONLY a JSON object:

{
  "field_name": "type and description",
  "evidence": ["plain text string 1", "plain text string 2"]
}

[Constraints in caps: EXACTLY one of "bullish", "neutral", "bearish"]
```

**Key prompt engineering rules for small models:**
1. **"Respond with ONLY a JSON object"** — prevents prose wrapping around JSON
2. **Explicit enum values** — "Use EXACTLY one of: X, Y, Z" prevents creative alternatives
3. **"Each evidence item must be a plain text STRING, not an object"** — prevents small models from returning `{"metric": "PE", "value": 95}` instead of `"PE ratio of 95x"`
4. **Only provide relevant data** — Worker 2a gets valuation metrics, not growth data. Less context = less confusion.
5. **Template placeholders** use `{{double_braces}}` — filled by `_fill_prompt()` at runtime

### Shared Schema Pattern

Workers 2a-2d all use `DimensionWorkerOutput`:

```python
class DimensionWorkerOutput(BaseModel):
    assessment: str = Field(min_length=3)
    evidence: list[str] = Field(min_length=1)
```

This means one normalizer handles all four. When a new dimension is needed, add a prompt file and reuse the same schema.

### Assembly Pattern

Each phase group has a `_assemble_stepN()` function that:
1. Extracts relevant worker results (with fallback defaults)
2. Merges them into the standard step-level schema
3. Adds any deterministic computations

The eval system only sees the standard schemas — it doesn't know about workers.

---

## Output Normalization

Small models produce messy outputs. The normalization layer (`_normalize_output()`) cleans them before Pydantic validation.

### Common Small-Model Issues & Fixes

| Issue | Example | Fix |
|-------|---------|-----|
| Field name aliases | `"buys": 30` instead of `"buy_count": 30` | Alias map: `{"buys": "buy_count", "buy": "buy_count", ...}` |
| String nulls | `"pe_ratio": "null"` | Convert `"null"/"None"/"N/A"/""` to Python `None` |
| Numeric strings | `"confidence": "0.72"` | `float()` conversion with try/except |
| Evidence as objects | `{"metric": "PE", "value": 95}` | Convert to `"PE: 95"` string |
| Evidence as string | `"evidence": "The PE is high"` | Wrap in list: `["The PE is high"]` |
| Invalid enums | `"trend": "slightly bullish"` | Keyword match: `"bull" in trend -> "bullish"` |
| Percentage confusion | `"confidence": 72` | Divide by 100 if > 1 |
| Price as number | `"entry_price": 370` | Wrap: `{"ideal": 370, "acceptable_range": [351.5, 388.5]}` |
| Missing defaults | `"magnitude": null` | Set defaults: `"medium"` |
| Catalyst as string | `"catalysts": "earnings beat"` | Wrap: `{"event": "earnings beat", "impact": "positive", "magnitude": "medium"}` |

### Normalization Architecture

```
LLM Output (raw dict)
    |
    v
_normalize_output(data, schema_class)
    |
    |--> Dispatch to schema-specific normalizer
    |    (e.g., _normalize_dimension_worker, _normalize_recommendation)
    |
    v
Cleaned dict
    |
    v
schema_class.model_validate(cleaned)
    |
    v
Validated Pydantic model
```

**Each worker schema has its own normalizer.** Normalizers are registered in a dispatch dict:

```python
normalizers = {
    NewsWorkerOutput: _normalize_news_worker,
    AnalystWorkerOutput: _normalize_analyst_worker,
    DimensionWorkerOutput: _normalize_dimension_worker,
    # ...
}
```

### Retry Strategy

Each LLM call gets 3 attempts. If normalization + validation fails, the same prompt is retried. With small schemas, the retry is fast and usually succeeds on attempt 2.

---

## Parallelism & Thread Safety

### ThreadPoolExecutor Pattern

```python
def _run_parallel_workers(adapter, system_prompt, worker_defs, max_workers=4):
    results, worker_stats = {}, {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for name, (prompt, schema_class) in worker_defs.items():
            worker_adapter = _clone_adapter(adapter)  # Thread safety!
            future = pool.submit(run_step, worker_adapter, system_prompt, prompt, schema_class, name)
            futures[future] = name
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results, worker_stats
```

### Thread Safety: Clone the Adapter

LLM adapters store mutable state (`self.last_usage`). Each worker gets a cloned adapter:

```python
def _clone_adapter(adapter):
    if isinstance(adapter, OllamaAdapter):
        return OllamaAdapter(model=adapter.model, base_url=adapter.base_url)
    return adapter  # API adapters are typically thread-safe
```

**For Ollama:** Requests still queue on a single GPU, but each worker's usage stats are isolated.
**For API providers:** Genuine parallelism with proper concurrency.

### Config

```yaml
workflow:
  parallel: true
  max_workers: 4
```

---

## Eval System

The eval system is model-agnostic and scores every pipeline output automatically.

### Layer 1: Deterministic Checks (12 checks)

Hard-coded, instant, 100% reproducible. No LLM involved.

| Check | What it verifies |
|-------|-----------------|
| `required_fields_present` | All schema fields non-empty |
| `recommendation_valid` | Must be buy/hold/sell/avoid |
| `risk_reward_math` | Ratio matches `(target - entry) / (entry - stop)` within +-0.3 |
| `position_size_pct_math` | Percentage matches `recommended / input` within +-0.02 |
| `price_ordering` | stop < entry < conservative < base |
| `confidence_bounds` | 0 <= confidence <= 1 |
| `stop_loss_below_entry` | 0 < stop < entry |
| `target_within_200pct` | Optimistic target <= 3x current price |
| `entry_near_current_price` | Entry within 15% of current price |
| `position_size_within_budget` | Recommended <= available |
| `has_recent_news` | At least 1 news item |
| `concentration_risk_mentioned` | If portfolio is tech-heavy and stock is tech, flag must be set |

### Layer 2: LLM-as-Judge (5 dimensions)

A different model scores the analysis quality on a 1-5 scale:

| Dimension | Weight | What it evaluates |
|-----------|--------|------------------|
| Causal Reasoning | 25% | Does the analysis explain why, not just what? |
| Information Completeness | 25% | Are all material events covered? |
| Actionability | 20% | Can a trader execute this recommendation directly? |
| Risk Awareness | 20% | Is the bear case as detailed as the bull case? |
| User Appropriateness | 10% | Does it match the user's risk tolerance and holdings? |

Pass threshold: weighted average >= 3.5

**Important:** The judge model must differ from the workflow model to avoid self-evaluation bias. In Ollama, this means using a different model (e.g., `qwen3:8b` judges `llama3.1:8b`).

### Judge Pool (Multiple Judges)

A single LLM judge introduces bias — different models have different scoring tendencies. The judge pool feature runs multiple judges in parallel and aggregates their scores:

```yaml
eval:
  judge_provider: ollama
  judge_models:        # Each model independently scores the analysis
    - qwen3:8b
    - llama3.1:8b
    - gemma2:9b
```

**How it works:**
1. Each judge model gets its own adapter (thread-safe, separate instances)
2. All judges run in parallel via `ThreadPoolExecutor`
3. Each calls `run_layer2()` independently — same rubric, same prompt
4. Results are aggregated: mean score per dimension, overall weighted average
5. `score_spread` = max - min of individual judge averages (detects disagreement)
6. Pass threshold: aggregated weighted average >= 3.5

**Backward compatibility:** Old `judge_model: single_model` config still works. Single-model configs skip the pool entirely and use the existing fast path.

**Partial failure:** If one judge crashes, the pool continues with the remaining judges. At least 1 must succeed.

**What the spread tells you:**
- Spread < 0.5 → strong consensus among judges
- Spread 0.5-1.0 → moderate disagreement, investigate individual justifications
- Spread > 1.0 → high disagreement, the analysis may be ambiguous or the rubric needs tuning

### Layer 3: Human Eval (Manual)

Template + gold-standard examples for calibrating the LLM judge. If judge scores diverge > 1 point from human scores, tune the rubric.

---

## Lessons Learned

### What Worked

1. **Deterministic computation eliminates hallucination.** RSI/MACD went from "frequently wrong" to "always correct" by computing in pandas instead of asking the LLM.

2. **Small schemas dramatically improve reliability.** 2-field schemas pass validation ~95% of the time on first attempt. 15-field schemas pass ~60% of the time.

3. **Normalization is the secret weapon.** Small models produce correct content in wrong formats. A normalization layer that handles aliases, type coercion, and structural transforms catches 90% of failures without retries.

4. **Deterministic concentration detection always passes eval.** The old LLM-based approach missed the `concentration_risk_mentioned` check ~40% of the time. The code-based approach passes 100% of the time.

5. **Worker prompt isolation prevents cross-contamination.** When Worker 2a only gets valuation data, it can't accidentally use growth metrics in its valuation assessment. Context isolation = cleaner output.

6. **The assembly pattern decouples workers from eval.** The eval system sees standard step-level schemas and doesn't know about workers. This means you can change the worker architecture without touching eval.

### What Surprised Us

1. **Fundamental rating was hard to make deterministic.** The keyword-matching heuristic (`_compute_fundamental_rating()`) works well enough but is the weakest link. A future improvement could use a 10th micro-worker with a 1-field schema (`{"rating": "strong | moderate | weak"}`).

2. **Evidence-as-objects was the #1 small-model failure mode.** Despite explicit prompts saying "plain text STRING", llama3.1:8b returns `{"metric": "PE", "value": 95}` about 30% of the time. The normalizer handles this, but it's the most common issue.

3. **Parallelism with Ollama doesn't speed things up much** (requests queue on the GPU), but the architecture still helps because each queued request is tiny and completes fast.

4. **Dry-run mode needs careful fixture splitting.** The old fixtures were step-level. Splitting them into worker-level data for dry-run mode requires understanding both the old and new schemas.

5. **Pipeline stats collection requires adapter cloning.** Without cloning, the `last_usage` dict gets overwritten by concurrent workers, producing incorrect stats.

### What to Watch Out For

1. **Adapter thread safety.** Always clone adapters for parallel workers. The `last_usage` dict is the main state conflict.

2. **Normalization must be exhaustive.** Every new failure mode in production needs a normalizer fix. Keep a list of observed failures and add handlers.

3. **Enum clamping is essential.** Small models love inventing enums like "slightly bullish" or "moderately strong". Always clamp to valid values with keyword matching.

4. **Prompt template filling must handle None.** The `_fill_prompt()` function converts `None` to the string `"N/A"` to prevent template corruption.

5. **Phase 4 prompt compression matters.** Worker 4a receives summaries from all 9 workers. Keep these summaries compact (1-2 sentences each) or the context overwhelms small models.

---

## Metrics: Before vs After

| Metric | Before (v1, sequential) | After (v2, swarm) |
|--------|------------------------|--------------------|
| LLM calls | 6 sequential | 11 (9 parallel + 2 sequential) |
| Sequential LLM depth | 6 | 3 |
| Avg output tokens/call | 300-500 | 50-150 |
| Schema fields/call | 8-15 | 2-5 |
| Deterministic code phases | 1 | 4 |
| RSI/MACD hallucination | Yes (~50% of runs) | None (computed in code) |
| Data passthrough waste | Step 1 copies yfinance | None |
| L1 eval pass rate (llama3.1:8b) | ~10/12 typical | 12/12 |
| L2 eval score (llama3.1:8b) | ~3.5/5.0 | ~3.7/5.0 |
| concentration_risk_mentioned | Fails ~40% of time | Always passes |

**Key result:** 12/12 deterministic checks on llama3.1:8b, up from ~10/12 with the old pipeline. The improvement comes entirely from moving math and data tasks to code.

---

## Applying This to Other Workflows

### Step 1: Identify What's Deterministic

For any LLM pipeline, ask:
- Which fields are computed from input data? (Move to code)
- Which fields are copy/paste from sources? (Move to code)
- Which fields require reasoning? (Keep as LLM workers)

### Step 2: Split Complex Prompts

If a prompt asks for more than 5 output fields, split it:
- Group related fields into mini-schemas
- Each group becomes a worker
- Independent groups run in parallel

### Step 3: Design the Dependency Graph

Draw which workers depend on which outputs:
- Independent workers -> parallel batch
- Dependent workers -> sequential after their dependencies

### Step 4: Build the Normalization Layer

For each worker schema, catalog the failure modes of your target model:
- Run 10-20 test calls
- Collect validation errors
- Write normalizers for each pattern

### Step 5: Add Deterministic Eval

Write checks that verify mathematical consistency without needing an LLM:
- Computed fields match their formulas
- Enums are valid
- Bounds are respected
- Cross-field relationships hold

### Template: Minimal Swarm Pipeline

```python
# Phase 0: Code
data = fetch_and_compute_deterministic_fields()

# Phase 1: Parallel LLM workers
workers = {
    "aspect_a": (prompt_a, SchemaA),
    "aspect_b": (prompt_b, SchemaB),
    "aspect_c": (prompt_c, SchemaC),
}
results = run_parallel(adapter, workers, max_workers=4)

# Phase 2: Sequential LLM (synthesis)
synthesis = run_step(adapter, synthesis_prompt(results), SynthesisSchema)

# Phase 3: Code (post-processing)
final = assemble_and_validate(results, synthesis)
```

---

## File Reference

```
stock-analysis-workflow/
|-- workflow-blueprint.md          # This file
|-- README.md                      # Quick start and usage guide
|-- config.yaml                    # Provider + workflow + eval config
|-- requirements.txt
|
|-- workflow/
|   |-- runner.py                  # Main orchestrator (phase-based)
|   |-- schema.py                  # Pydantic schemas (step-level + worker-level)
|   |-- indicators.py              # RSI, MACD, SMA, volume, pivots (pure code)
|   |-- concentration.py           # Sector overlap detection (pure code)
|   +-- prompts/
|       |-- system.md              # System prompt for all workers
|       |-- worker_1a_news.md      # -> NewsWorkerOutput
|       |-- worker_1b_analyst.md   # -> AnalystWorkerOutput
|       |-- worker_2a_valuation.md # -> DimensionWorkerOutput
|       |-- worker_2b_growth.md    # -> DimensionWorkerOutput
|       |-- worker_2c_moat.md      # -> DimensionWorkerOutput
|       |-- worker_2d_balance.md   # -> DimensionWorkerOutput
|       |-- worker_3a_technical.md # -> TechInterpretationOutput
|       |-- worker_3b_catalysts.md # -> CatalystWorkerOutput
|       |-- worker_3c_risks.md     # -> RiskWorkerOutput
|       |-- step5a_recommendation.md # -> RecommendationOutput (Phase 4a)
|       |-- step5b_narrative.md    # -> NarrativeOutput (Phase 4b)
|       +-- (legacy step1-4 prompts kept for reference)
|
|-- eval/
|   |-- run_eval.py                # Eval orchestrator
|   |-- layer1_deterministic.py    # 12 hard-coded checks
|   |-- layer2_llm_judge.py        # LLM scoring (5 dimensions)
|   |-- layer2_rubric.md           # Judge rubric prompt
|   |-- report.py                  # Report generator
|   +-- layer3_human/
|       |-- template.md            # Human grading template
|       +-- examples/              # Gold-standard calibration examples
|
|-- adapters/
|   |-- base.py                    # Abstract LLM interface
|   |-- anthropic_adapter.py       # Claude
|   |-- openai_adapter.py          # GPT
|   +-- ollama_adapter.py          # Local models (Ollama)
|
|-- compare/
|   +-- cross_model_compare.py     # Run same analysis across models
|
|-- tests/
|   +-- fixtures/                  # Mock data for dry-run mode
|
+-- results/                       # Stored outputs + eval scores
```
