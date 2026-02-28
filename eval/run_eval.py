"""Eval orchestrator — runs all eval layers."""

import copy
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.layer1_deterministic import run_layer1
from eval.layer2_llm_judge import run_layer2, run_layer2_pool
from workflow.schema import AnalysisResult, EvalReport

logger = logging.getLogger(__name__)


def _resolve_judge_models(config: dict) -> tuple:
    """Resolve judge model list from config (backward compatible).

    Supports:
      - judge_models: [model1, model2]   (new: pool)
      - judge_model: model1              (old: single)
      - neither: use provider's default_model

    Returns:
        (judge_provider, judge_models_list) or (None, []) if no judge configured.
    """
    eval_config = config.get("eval", {})
    judge_provider = eval_config.get("judge_provider")

    if not judge_provider:
        return None, []

    judge_models = eval_config.get("judge_models")  # New: list
    judge_model = eval_config.get("judge_model")     # Old: string

    if judge_models and isinstance(judge_models, list):
        return judge_provider, judge_models
    elif judge_model:
        return judge_provider, [judge_model]
    else:
        # Use provider's default model
        default_model = config.get("providers", {}).get(judge_provider, {}).get("default_model")
        if default_model:
            return judge_provider, [default_model]
        return judge_provider, []


def run_eval(result: AnalysisResult, config: dict) -> EvalReport:
    """Run all eval layers on an analysis result."""

    # Layer 1: Deterministic checks
    logger.info("  Layer 1: Deterministic checks...")
    layer1_result = run_layer1(result)

    failed_checks = [
        name for name, check in layer1_result.checks.items() if not check["passed"]
    ]
    if failed_checks:
        logger.warning(f"  Layer 1 FAILED checks: {', '.join(failed_checks)}")
    else:
        logger.info(f"  Layer 1 PASSED ({layer1_result.passed_checks}/{layer1_result.total_checks} checks)")

    # Layer 2: LLM-as-Judge (single or pool)
    layer2_result = None
    layer2_pool_result = None

    judge_provider, judge_models = _resolve_judge_models(config)

    # Skip any judge model that is the same as the worker model
    # (self-evaluation bias: a model tends to rate its own output higher)
    worker_model = result.model_name
    if judge_models and worker_model:
        filtered = [m for m in judge_models if m != worker_model]
        if len(filtered) < len(judge_models):
            skipped = [m for m in judge_models if m == worker_model]
            logger.info(
                f"  Skipping judge(s) matching worker model: {', '.join(skipped)}"
            )
            judge_models = filtered

    if judge_provider and not judge_models:
        logger.info("  Layer 2 skipped (all judges match worker model)")

    if judge_provider and judge_models:
        try:
            from adapters import OllamaAdapter
            from workflow.runner import create_adapter

            # Create one adapter per judge model
            judge_adapters = []
            for model in judge_models:
                model_config = copy.deepcopy(config)
                model_config["providers"][judge_provider]["default_model"] = model
                adapter = create_adapter(judge_provider, model_config)
                judge_adapters.append(adapter)

            # Scale timeout for Ollama pool: single GPU queues requests,
            # so the last judge may wait for all others to finish first.
            # timeout = base_timeout * num_judges (300s per judge slot).
            if len(judge_adapters) > 1:
                for adapter in judge_adapters:
                    if isinstance(adapter, OllamaAdapter):
                        adapter.timeout = 300 * len(judge_adapters)

            if len(judge_adapters) == 1:
                # Single judge — use existing fast path (no pool overhead)
                model_name = judge_models[0]
                logger.info(f"  Layer 2: LLM-as-Judge (using {judge_provider}, model={model_name})...")
                layer2_result = run_layer2(result, judge_adapters[0], l1_result=layer1_result)
                logger.info(
                    f"  Layer 2 {'PASSED' if layer2_result.passed else 'FAILED'} "
                    f"(score: {layer2_result.overall_weighted_average:.2f}/5.0)"
                )
            else:
                # Pool of judges — run in parallel
                logger.info(
                    f"  Layer 2: LLM Judge Pool ({len(judge_adapters)} judges: "
                    f"{', '.join(judge_models)})..."
                )
                layer2_pool_result = run_layer2_pool(
                    result, judge_adapters, max_workers=len(judge_adapters),
                    l1_result=layer1_result,
                )
                # Populate layer2 with first individual result for backward compat
                layer2_result = layer2_pool_result.individual_results[0]
                logger.info(
                    f"  Layer 2 {'PASSED' if layer2_pool_result.passed else 'FAILED'} "
                    f"(pool avg: {layer2_pool_result.overall_weighted_average:.2f}/5.0, "
                    f"{layer2_pool_result.num_succeeded}/{layer2_pool_result.num_judges} judges, "
                    f"spread: {layer2_pool_result.score_spread:.2f})"
                )
        except Exception as e:
            logger.warning(f"  Layer 2 skipped due to error: {e}")
    elif not judge_provider:
        logger.info("  Layer 2 skipped (no judge_provider configured)")

    # Overall pass: Layer 1 must pass, Layer 2 must pass if it ran
    overall_passed = layer1_result.passed
    if layer2_pool_result is not None:
        overall_passed = overall_passed and layer2_pool_result.passed
    elif layer2_result is not None:
        overall_passed = overall_passed and layer2_result.passed

    report = EvalReport(
        ticker=result.ticker,
        model_name=result.model_name,
        timestamp=datetime.now().isoformat(),
        layer1=layer1_result,
        layer2=layer2_result,
        layer2_pool=layer2_pool_result,
        overall_passed=overall_passed,
    )

    return report
