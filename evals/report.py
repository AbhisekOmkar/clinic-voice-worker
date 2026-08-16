"""Run-directory reports: results.json (machine) + REPORT.md (human), with
per-language breakdowns and an explicit false-confidence section."""

import json
import statistics
from dataclasses import asdict
from pathlib import Path

from evals.runner import ScenarioResult


def _p50(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def language_rollup(results: list[ScenarioResult]) -> dict:
    rollup = {}
    for language in ("en", "hi", "mixed"):
        rows = [r for r in results if r.language == language]
        if not rows:
            continue
        redundant_counts = [len(r.redundant_questions) for r in rows if r.redundant_questions is not None]
        judged_language_rows = [r for r in rows if r.language_violations is not None]
        ttfts = [t for r in rows for t in r.llm_ttft_ms]
        completions = [r.turns_to_completion for r in rows if r.turns_to_completion]
        rollup[language] = {
            "scenarios": len(rows),
            "passed": sum(1 for r in rows if r.passed),
            "task_success_rate": round(sum(1 for r in rows if r.passed) / len(rows), 2),
            "avg_turns_to_completion": round(statistics.mean(completions), 1) if completions else None,
            "redundant_question_rate": (
                round(sum(redundant_counts) / len(redundant_counts), 2) if redundant_counts else None
            ),
            "language_violation_count": (
                sum(len(r.language_violations) for r in judged_language_rows)
                if judged_language_rows
                else None
            ),
            "script_drift_count": sum(len(r.script_language_violations) for r in rows),
            "llm_ttft_ms_p50": _p50(ttfts),
            "hindi_quality_avg": (
                round(
                    statistics.mean([r.hindi_quality for r in rows if r.hindi_quality]),
                    1,
                )
                if any(r.hindi_quality for r in rows)
                else None
            ),
        }
    return rollup


FALSE_CONFIDENCE = """## Where this harness gives false confidence

- **Text mode skips the ears and mouth.** These runs exercise prompt, LLM, tools,
  backend and database — but not STT mishearings, TTS pronunciation, barge-in or
  endpointing. A perfect score here can still stutter on a real call. Component
  latency probes and live-call metrics (call_latency_metrics) cover that gap
  partially; only live calls close it.
- **Scripted callers are cooperative.** Turns provide information the way the
  script author expected. Real callers ramble, self-correct and talk over the
  agent; turns-to-completion here is a lower bound.
- **LLM judges share DNA with the agent.** The judge model can be blind to the
  same Hindi awkwardness the agent produces. Deterministic script-drift counts
  are reported alongside for that reason; treat judge zeros as "nothing obvious",
  not "perfect".
- **One run is one sample.** LLMs are stochastic; a pass at temperature 0.3 is
  not a guarantee. Re-run with --repeat for stability checks before drawing
  conclusions from a single green table.
- **Latency numbers in this report are LLM TTFT only.** End-to-end voice latency
  adds EOU detection, STT finalisation, TTS TTFB and network — see the latency
  probe report and per-call metrics for those components.
"""


def write_reports(results: list[ScenarioResult], run_dir: Path, meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    rollup = language_rollup(results)
    payload = {
        "meta": meta,
        "per_language": rollup,
        "scenarios": [asdict(r) for r in results],
    }
    (run_dir / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    lines = ["# Eval report", ""]
    lines.append(f"- run: `{meta.get('run_id')}`  ")
    lines.append(f"- model: `{meta.get('llm_model')}`  ")
    lines.append(f"- started: {meta.get('started_at')}  ")
    lines.append("")
    lines.append("## Per-language summary")
    lines.append("")
    lines.append("| language | scenarios | passed | success | avg turns→done | redundant Q/call | judge lang violations | script drift | LLM TTFT p50 (ms) | hindi quality |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for language, stats in rollup.items():
        lines.append(
            f"| {language} | {stats['scenarios']} | {stats['passed']} | {stats['task_success_rate']} | "
            f"{stats['avg_turns_to_completion']} | {stats['redundant_question_rate']} | "
            f"{stats['language_violation_count']} | {stats['script_drift_count']} | "
            f"{stats['llm_ttft_ms_p50']} | {stats['hindi_quality_avg']} |"
        )
    lines.append("")
    lines.append("## Scenarios")
    lines.append("")
    lines.append("| scenario | lang | passed | completed | turns→done | redundant | lang issues | notes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        notes = "; ".join(r.tool_expectation_failures + r.db_assertion_failures)[:160]
        if r.error:
            notes = f"ERROR: {r.error[:120]}"
        redundant = len(r.redundant_questions) if r.redundant_questions is not None else "—"
        language_issues = (
            len(r.language_violations) if r.language_violations is not None else "—"
        )
        lines.append(
            f"| {r.scenario_id} | {r.language} | {'✅' if r.passed else '❌'} | "
            f"{'✅' if r.completed else '—'} | {r.turns_to_completion or '—'} | "
            f"{redundant} | {language_issues} | {notes} |"
        )
    lines.append("")
    lines.append(FALSE_CONFIDENCE)
    (run_dir / "REPORT.md").write_text("\n".join(lines))

    for r in results:
        transcript_lines = [f"# {r.scenario_id} ({'PASS' if r.passed else 'FAIL'})", ""]
        for turn in r.transcript:
            transcript_lines.append(f"**{turn['role']}** [{turn['lang']}]: {turn['text']}")
            transcript_lines.append("")
        transcript_lines.append("## Tool calls")
        for call in r.tool_calls:
            transcript_lines.append(f"- `{call['name']}` {json.dumps(call['args'], ensure_ascii=False)}")
        (run_dir / f"transcript_{r.scenario_id}.md").write_text("\n".join(transcript_lines))
