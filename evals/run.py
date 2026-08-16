"""Eval CLI.

    poetry run python -m evals.run                       # all scenarios
    poetry run python -m evals.run --only dropped_call   # substring filter
    poetry run python -m evals.run --list

Requires the platform backend running (make -C ../clinic-platform-backend run)
with seeded clinic data. Uses the real LLM — costs a few paise per scenario.
"""

import argparse
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from evals.report import write_reports
from evals.runner import ScenarioRunner, load_scenario
from evals.seeding import Backend

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
RUNS_DIR = Path(__file__).parent / "runs"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default=str(SCENARIOS_DIR))
    parser.add_argument("--only", default=None, help="substring filter on scenario id")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    paths = sorted(Path(args.scenarios).glob("*.yaml"))
    scenarios = [load_scenario(str(p)) for p in paths]
    if args.only:
        scenarios = [s for s in scenarios if args.only in s["id"]]
    if args.list:
        for s in scenarios:
            print(f"{s['id']:40s} [{s.get('language')}] {s.get('description', '')}")
        return 0
    if not scenarios:
        print("No scenarios matched.")
        return 1

    backend = Backend()
    try:
        await backend.client.get("/branches")
    except Exception:
        print("Backend not reachable at PLATFORM_URL — start clinic-platform-backend first (make run).")
        return 1

    from app.config.settings import settings

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    runner = ScenarioRunner(backend)
    results = []
    started = time.time()
    for scenario in scenarios:
        logger.info(f"▶ {scenario['id']}")
        result = await runner.run(scenario)
        status = "PASS" if result.passed else "FAIL"
        logger.info(
            f"■ {scenario['id']}: {status} completed={result.completed} "
            f"turns_to_completion={result.turns_to_completion} "
            f"failures={result.tool_expectation_failures + result.db_assertion_failures}"
        )
        results.append(result)

    meta = {
        "run_id": run_id,
        "llm_model": settings.llm_model,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - started, 1),
        "scenario_count": len(results),
    }
    write_reports(results, run_dir, meta)
    await backend.aclose()

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} scenarios passed — report at {run_dir}/REPORT.md")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
