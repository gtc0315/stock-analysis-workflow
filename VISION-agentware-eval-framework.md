# Agentware Vision & Eval Framework

## The Problem

Today, people interact with LLMs ad-hoc. Every prompt is improvised, every workflow lives in someone's head, quality is inconsistent, and nothing is reusable. When you switch from Claude to GPT, you start over. When a colleague wants your process, you can't hand it to them in a runnable form.

This is the equivalent of the software industry before version control, package managers, and testing frameworks existed — everyone writing one-off scripts with no structure, no quality assurance, and no way to share or build on each other's work.

## The Concept: Agentware

Agentware is a standardized layer that sits between the user and the LLM:

```
User → Agentware (workflows + eval) → Any LLM → Output
```

It is NOT a product or an app. It is a layer — like how software is a layer between humans and hardware. The key properties:

- **Workflows are portable.** A workflow written once runs on Claude, GPT, Gemini, Llama, or any future model. Switching models is a config change, not a rewrite.
- **Knowledge is encoded, not improvised.** Domain experts (investors, doctors, lawyers, engineers) capture their expertise as structured, repeatable workflows — not as prompts they type from memory each time.
- **Quality is measurable.** Every workflow output is automatically evaluated. You know whether the result is trustworthy before you act on it.

The key distinction from traditional software: software is deterministic (human writes exact rules, computer follows them). Agentware is directive (human sets goals and quality standards, AI decides how to execute). This makes it capable of handling complex, judgment-heavy tasks that traditional software cannot.

## Why Eval is the First Priority

Standards and protocols matter, but they emerge from practice, not committees. The agentware ecosystem's most urgent gap is **eval** — the ability to measure whether an AI-driven workflow actually produces good output.

Without eval:
- You can't compare workflows (is mine better than yours?)
- You can't compare models (does it matter if I use Claude vs GPT?)
- You can't improve over time (what should I change to get better results?)
- You can't trust the output (is this analysis reliable enough to act on?)

With eval, standards emerge naturally — because the moment you try to evaluate two workflows side by side, you need them to share input/output formats, quality dimensions, and scoring rubrics. Eval forces standardization from the bottom up.

## The Three-Layer Eval Architecture

AI workflow outputs cannot be evaluated by code alone (too rigid) or by LLMs alone (not deterministic). The solution is a layered system where each layer catches different classes of errors:

### Layer 1: Deterministic Checks (Code)
Fast, cheap, 100% reproducible. Catches obvious failures:
- Schema/format validation (are all required fields present?)
- Mathematical consistency (do the numbers add up?)
- Boundary checks (are values within reasonable ranges?)
- Data freshness (is the analysis using current data?)
- Constraint alignment (does the output respect user-specified constraints?)

This layer filters out ~30-40% of bad outputs before anything more expensive runs.

### Layer 2: LLM-as-Judge
Uses a DIFFERENT model from the one that generated the output to score quality across defined rubric dimensions. Key design choices:
- Judge model must differ from generator model (same model judging itself has systematic bias)
- Rubric must be specific and dimensional, not "is this good?" — e.g., score causal reasoning, information completeness, actionability, risk awareness separately
- Outputs numerical scores with brief justifications

### Layer 3: Human Eval (Periodic Calibration)
Domain experts periodically grade outputs to create gold-standard examples. These serve two purposes:
1. Calibrate the LLM judge — if judge scores diverge from human scores, the rubric needs tuning
2. Establish ground truth for what "good" looks like in this specific domain

Over time, insights from Layer 3 sink into Layer 2 (better rubrics), and from Layer 2 into Layer 1 (new deterministic rules). The system gets cheaper and faster while quality improves.

## The Bigger Hypothesis

If you run the same workflow across multiple LLMs and the eval scores are similar, it suggests that **the workflow matters more than the model**. This has profound implications:

- LLMs commoditize — value shifts from model providers to workflow creators
- Domain expertise becomes the scarce asset, not compute or model architecture
- The agentware layer (workflows + eval standards) becomes the durable, accumulating source of value

This project is a first concrete test of that hypothesis, using stock analysis as the domain.

## What This Project Is

A reference implementation — the first open-source workflow that ships with built-in eval. It demonstrates:

1. How to structure an LLM-agnostic workflow with strict input/output schemas
2. How to implement three-layer eval for a real domain
3. How to compare model performance on identical tasks with identical quality criteria

It is intentionally scoped to one domain (investment analysis) to stay concrete and useful. But the architecture — workflow runner, adapter interface, eval layers, cross-model comparison — is designed to be a template that others can fork for their own domains.

## Long-Term Ecosystem Vision

If this pattern proves useful, the natural next steps are:

- **Workflow Registry** — a public repository where domain experts contribute evaluated workflows (like npm for agent workflows)
- **Universal Eval Standard** — a shared format for eval rubrics and scoring so workflows across domains can be compared and composed
- **Community-contributed eval rubrics** — domain experts define "what good looks like" for their field, which is arguably more valuable than the workflows themselves

None of this needs to be built now. The first step is one working workflow with one working eval, for one real domain. Everything else grows from there.
