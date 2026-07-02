from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from edge_assistant.config import load_config
from edge_assistant.metrics import ProcessCpuMonitor
from edge_assistant.pipeline import AlwaysOnPipeline


def run_benchmark(config_path: str, mode: str, duration_s: float) -> dict:
    config = load_config(config_path)
    interval_s = config.benchmark.sample_interval_ms / 1000.0
    started = time.time()
    with ProcessCpuMonitor(interval_s=interval_s) as cpu:
        stats = AlwaysOnPipeline(config, mode=mode).run(duration_s)
    cpu_summary = cpu.summary
    limit = (
        config.benchmark.background_cpu_limit_percent
        if mode == "background"
        else config.benchmark.active_cpu_limit_percent
    )
    result = {
        "mode": mode,
        "duration_s": duration_s,
        "started_at": started,
        "cpu_avg_percent_of_total": cpu_summary.avg_percent,
        "cpu_max_percent_of_total": cpu_summary.max_percent,
        "cpu_limit_percent_of_total": limit,
        "cpu_pass": cpu_summary.avg_percent <= limit,
        "pipeline": stats.to_dict(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark always-on edge pipeline")
    parser.add_argument("--config", default="configs/pipeline.sim.toml")
    parser.add_argument("--mode", choices=["background", "active"], default="active")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    result = run_benchmark(args.config, args.mode, args.duration)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if result["cpu_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
