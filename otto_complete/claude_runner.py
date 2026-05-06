import json
import logging
import subprocess

from otto_complete.budget import BudgetTracker
from otto_complete.config import Config
from otto_complete.metrics import record_run

log = logging.getLogger(__name__)

_budget: BudgetTracker | None = None


def set_budget_tracker(tracker: BudgetTracker):
    global _budget
    _budget = tracker


def run_claude(
    config: Config,
    bot: str,
    issue_key: str,
    prompt: str,
    tools: str,
    max_turns: int,
    max_budget: str,
) -> tuple[int, dict]:
    if _budget and not _budget.can_spend(float(max_budget)):
        log.warning("Global budget exhausted ($%.2f / $%.2f) — skipping %s/%s",
                     _budget.spent, _budget.max_budget, bot, issue_key)
        return 1, {}

    cmd = [
        "claude", "-p", prompt,
        "--plugin-dir", "/opt/superpowers",
        "--allowedTools", tools,
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(max_budget),
        "--output-format", "json",
    ]

    log.info("Running Claude for %s/%s (max %d turns, $%s budget)", bot, issue_key, max_turns, max_budget)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=config.clone_path, timeout=1800,
        )
        exit_code = result.returncode
        output = {}
        if result.stdout.strip():
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                log.warning("Failed to parse Claude JSON output")
    except subprocess.TimeoutExpired:
        log.error("Claude timed out for %s/%s", bot, issue_key)
        exit_code = 1
        output = {}
    except Exception as e:
        log.error("Claude failed for %s/%s: %s", bot, issue_key, e)
        exit_code = 1
        output = {}

    record_run(bot, issue_key, output, exit_code)

    if _budget:
        _budget.record(output.get("total_cost_usd", 0.0))

    if exit_code != 0:
        log.warning("Claude exited with code %d for %s/%s (may still have produced changes)", exit_code, bot, issue_key)

    return exit_code, output
