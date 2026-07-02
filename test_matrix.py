from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

from edge_voice_test.metrics import write_csv


def run_one(quant: str, threads: int, loops: int, duration: float, time_scale: float) -> dict:
    out = Path("results") / f"matrix_{quant}_t{threads}.csv"
    cmd = [
        sys.executable,
        "benchmarks/benchmark_pipeline.py",
        "--asr-backend",
        "simulated",
        "--tts-backend",
        "simulated",
        "--quant", quant,
        "--threads", str(threads),
        "--loops", str(loops),
        "--duration", str(duration),
        "--time-scale", str(time_scale),
        "--warm-up-loops", "1",
        "--out", str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    import json
    return json.loads(proc.stdout)


def main() -> None:
    summaries = []
    for quant, threads in itertools.product(["FP16", "Q8", "Q5", "Q4"], [1, 2, 3, 4]):
        summaries.append(run_one(quant, threads, loops=10, duration=5.0, time_scale=0.01))
    write_csv(summaries, "results/matrix_summary.csv")
    print("Wrote results/matrix_summary.csv")
    for s in summaries:
        print(f"{s['quant']:>4} t{s['threads']}: RTF={s['mean_rtf']:.3f} pass={s['rtf_pass']} RAM slope={s['ram_slope_mb_per_loop']:.4f} MB/loop")


if __name__ == "__main__":
    main()
