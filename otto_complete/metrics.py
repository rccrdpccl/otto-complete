import logging
import threading

from prometheus_client import Counter, Histogram, start_http_server

log = logging.getLogger(__name__)

runs_total = Counter(
    "otto_runs_total",
    "Total Claude runs",
    ["bot", "status"],
)
cost_usd = Histogram(
    "otto_run_cost_usd",
    "Cost per run in USD",
    ["bot"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0],
)
duration_seconds = Histogram(
    "otto_run_duration_seconds",
    "Wall-clock duration per run",
    ["bot"],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 1800],
)
turns = Histogram(
    "otto_run_turns",
    "Number of turns per run",
    ["bot"],
    buckets=[1, 5, 10, 15, 20, 30, 50],
)
input_tokens = Counter(
    "otto_input_tokens_total",
    "Total input tokens",
    ["bot", "model"],
)
output_tokens = Counter(
    "otto_output_tokens_total",
    "Total output tokens",
    ["bot", "model"],
)


def record_run(bot: str, issue_key: str, output: dict, exit_code: int):
    status = "success" if exit_code == 0 else "failure"
    runs_total.labels(bot=bot, status=status).inc()
    cost_usd.labels(bot=bot).observe(output.get("total_cost_usd", 0))
    duration_seconds.labels(bot=bot).observe(output.get("duration_ms", 0) / 1000.0)
    turns.labels(bot=bot).observe(output.get("num_turns", 0))

    for model, usage in output.get("modelUsage", {}).items():
        input_tokens.labels(bot=bot, model=model).inc(usage.get("inputTokens", 0))
        output_tokens.labels(bot=bot, model=model).inc(usage.get("outputTokens", 0))


_metrics_started = False


def start_metrics_server(port: int = 9090):
    global _metrics_started
    if _metrics_started:
        return
    _metrics_started = True

    def _start():
        try:
            start_http_server(port)
            log.info("Metrics server listening on :%d", port)
        except Exception as e:
            log.error("Failed to start metrics server: %s", e)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
