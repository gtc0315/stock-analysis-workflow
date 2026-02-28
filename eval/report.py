"""Generate eval summary report."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflow.schema import EvalReport

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def generate_report(eval_report: EvalReport) -> str:
    """Generate a human-readable eval report."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  EVALUATION REPORT: {eval_report.ticker}")
    lines.append(f"  Model: {eval_report.model_name}")
    lines.append(f"  Timestamp: {eval_report.timestamp}")
    lines.append("=" * 60)

    # Layer 1
    l1 = eval_report.layer1
    lines.append(f"\n  Layer 1: Deterministic Checks — {'PASS' if l1.passed else 'FAIL'}")
    lines.append(f"  {l1.passed_checks}/{l1.total_checks} checks passed\n")

    for name, check in l1.checks.items():
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"    [{status}] {name}")
        if not check["passed"]:
            lines.append(f"           {check['reason']}")

    # Layer 2
    l2_pool = getattr(eval_report, "layer2_pool", None)

    if l2_pool:
        lines.append(f"\n  Layer 2: LLM Judge Pool — {'PASS' if l2_pool.passed else 'FAIL'}")
        lines.append(f"  Pool Score: {l2_pool.overall_weighted_average:.2f}/5.0")
        lines.append(f"  Judges: {l2_pool.num_succeeded}/{l2_pool.num_judges} succeeded")
        lines.append(f"  Score Spread: {l2_pool.score_spread:.2f}\n")

        dimensions = [
            ("Causal Reasoning (25%)",     l2_pool.causal_reasoning),
            ("Info Completeness (25%)",    l2_pool.information_completeness),
            ("Actionability (20%)",        l2_pool.actionability),
            ("Risk Awareness (20%)",       l2_pool.risk_awareness),
            ("User Appropriateness (10%)", l2_pool.user_appropriateness),
        ]
        for name, dim in dimensions:
            lines.append(f"    {name}: {dim.mean_score:.1f}/5  [{dim.min_score}-{dim.max_score}]")

        lines.append(f"\n  Individual Judge Scores:")
        for jr in l2_pool.individual_results:
            lines.append(f"    {jr.judge_model}: {jr.overall_weighted_average:.2f}/5.0 "
                         f"({'PASS' if jr.passed else 'FAIL'})")
            judge_dims = [
                ("Causal Reasoning", jr.causal_reasoning),
                ("Info Completeness", jr.information_completeness),
                ("Actionability", jr.actionability),
                ("Risk Awareness", jr.risk_awareness),
                ("User Appropriateness", jr.user_appropriateness),
            ]
            for dname, ddim in judge_dims:
                lines.append(f"      {dname}: {ddim.score}/5")
                if ddim.sub_items:
                    for item_name, item in ddim.sub_items.items():
                        status = "PASS" if item.met else "FAIL"
                        lines.append(f"        [{status}] {item_name}: {item.note}")
                elif ddim.justification:
                    lines.append(f"        {ddim.justification}")
    elif eval_report.layer2:
        l2 = eval_report.layer2
        lines.append(f"\n  Layer 2: LLM-as-Judge — {'PASS' if l2.passed else 'FAIL'}")
        lines.append(f"  Overall Score: {l2.overall_weighted_average:.2f}/5.0")
        lines.append(f"  Judge Model: {l2.judge_model}\n")

        dimensions = [
            ("Causal Reasoning (25%)", l2.causal_reasoning),
            ("Info Completeness (25%)", l2.information_completeness),
            ("Actionability (20%)", l2.actionability),
            ("Risk Awareness (20%)", l2.risk_awareness),
            ("User Appropriateness (10%)", l2.user_appropriateness),
        ]
        for name, dim in dimensions:
            lines.append(f"    {name}: {dim.score}/5")
            if dim.sub_items:
                for item_name, item in dim.sub_items.items():
                    status = "PASS" if item.met else "FAIL"
                    lines.append(f"      [{status}] {item_name}: {item.note}")
            elif dim.justification:
                lines.append(f"      {dim.justification}")
    else:
        lines.append("\n  Layer 2: LLM-as-Judge — SKIPPED")

    # Overall
    lines.append(f"\n  OVERALL: {'PASSED' if eval_report.overall_passed else 'FAILED'}")
    lines.append("=" * 60)

    return "\n".join(lines)


def print_report(eval_report: EvalReport):
    """Print eval report to stdout."""
    print(generate_report(eval_report))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Print eval report from JSON file")
    parser.add_argument("eval_file", type=str, help="Path to eval JSON file")
    args = parser.parse_args()

    with open(args.eval_file) as f:
        data = json.load(f)
    report = EvalReport.model_validate(data)
    print_report(report)
