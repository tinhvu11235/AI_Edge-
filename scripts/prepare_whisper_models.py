from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


QUANT_TARGETS = {
    "FP16": {"suffix": "", "whisper_cpp_quant": "", "wer_delta_estimate": 0.0},
    "Q8": {"suffix": "q8_0", "whisper_cpp_quant": "q8_0", "wer_delta_estimate": 0.004},
    "Q5": {"suffix": "q5_0", "whisper_cpp_quant": "q5_0", "wer_delta_estimate": 0.012},
    "Q4": {"suffix": "q4_0", "whisper_cpp_quant": "q4_0", "wer_delta_estimate": 0.026},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quantize Whisper Tiny and select a deployment model")
    p.add_argument("--model-in", default="models/whisper/ggml-tiny.bin")
    p.add_argument("--quantize-bin", default="")
    p.add_argument("--out-dir", default="models/whisper")
    p.add_argument("--results-dir", default="results/model_prep")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--loops", type=int, default=10)
    p.add_argument("--time-scale", type=float, default=0.01)
    p.add_argument("--wer-threshold", type=float, default=0.02)
    p.add_argument("--rtf-threshold", type=float, default=0.3)
    p.add_argument("--skip-quantize", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    model_in = Path(args.model_in)
    out_dir = Path(args.out_dir)
    results_dir = Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    quantize_bin = resolve_quantize_bin(args.quantize_bin)
    artifacts = prepare_artifacts(model_in, out_dir, quantize_bin, args.skip_quantize)
    experiments = run_experiments(args, artifacts, results_dir)
    selection = select_model(experiments, args.wer_threshold, args.rtf_threshold)

    report = {
        "source_model": str(model_in),
        "quantize_bin": str(quantize_bin) if quantize_bin else "",
        "wer_threshold": args.wer_threshold,
        "rtf_threshold": args.rtf_threshold,
        "artifacts": artifacts,
        "experiments": experiments,
        "selected": selection,
    }
    report_path = results_dir / "model_prep_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_experiment_csv(experiments, results_dir / "model_prep_summary.csv")
    (out_dir / "selected_model.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def resolve_quantize_bin(configured: str) -> Path | None:
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path("third_party/whisper.cpp/build/bin/whisper-quantize"),
            Path("third_party/whisper.cpp/build/bin/quantize"),
            Path("/opt/whisper.cpp/build/bin/whisper-quantize"),
            Path("/opt/whisper.cpp/build/bin/quantize"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def prepare_artifacts(
    model_in: Path,
    out_dir: Path,
    quantize_bin: Path | None,
    skip_quantize: bool,
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {
        "FP16": {
            "path": str(model_in),
            "exists": model_in.exists(),
            "created": False,
            "quantized": False,
        }
    }
    if not model_in.exists():
        raise FileNotFoundError(f"Base model not found: {model_in}")

    for label, meta in QUANT_TARGETS.items():
        if label == "FP16":
            continue
        out_path = out_dir / f"{model_in.stem}-{meta['suffix']}{model_in.suffix}"
        created = False
        if not out_path.exists() and not skip_quantize:
            if quantize_bin is None:
                raise FileNotFoundError(
                    "quantize binary not found. Run scripts/build_whisper_cpp.sh or pass --quantize-bin."
                )
            subprocess.run(
                [str(quantize_bin), str(model_in), str(out_path), str(meta["whisper_cpp_quant"])],
                check=True,
            )
            created = True
        artifacts[label] = {
            "path": str(out_path),
            "exists": out_path.exists(),
            "created": created,
            "quantized": True,
            "whisper_cpp_quant": meta["whisper_cpp_quant"],
        }
    return artifacts


def run_experiments(
    args: argparse.Namespace,
    artifacts: dict[str, dict[str, Any]],
    results_dir: Path,
) -> list[dict[str, Any]]:
    experiments = []
    for label in ["FP16", "Q8", "Q5", "Q4"]:
        artifact = artifacts[label]
        if not artifact["exists"]:
            experiments.append(
                {
                    "quant": label,
                    "artifact_path": artifact["path"],
                    "artifact_exists": False,
                    "status": "missing_artifact",
                }
            )
            continue
        csv_path = results_dir / f"benchmark_{label.lower()}_t{args.threads}.csv"
        cmd = [
            sys.executable,
            "benchmarks/benchmark_pipeline.py",
            "--asr-backend",
            "simulated",
            "--tts-backend",
            "simulated",
            "--quant",
            label,
            "--threads",
            str(args.threads),
            "--duration",
            str(args.duration),
            "--loops",
            str(args.loops),
            "--time-scale",
            str(args.time_scale),
            "--out",
            str(csv_path),
            "--redact-transcript",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        summary = json.loads(proc.stdout)
        summary["artifact_path"] = artifact["path"]
        summary["artifact_exists"] = True
        summary["status"] = "ok"
        experiments.append(summary)
    return experiments


def select_model(
    experiments: list[dict[str, Any]],
    wer_threshold: float,
    rtf_threshold: float,
) -> dict[str, Any]:
    candidates = []
    for row in experiments:
        if row.get("status") != "ok":
            continue
        wer_delta = row.get("wer_delta_estimate")
        if wer_delta is None:
            continue
        if (
            row.get("mean_rtf", 999.0) < rtf_threshold
            and wer_delta <= wer_threshold
            and row.get("memory_leak_pass_simple") is True
            and row.get("load_once_pass") is True
        ):
            candidates.append(row)
    if not candidates:
        return {"status": "no_candidate", "reason": "No quant passed RTF/WER/memory/load-once gates."}
    selected = sorted(candidates, key=lambda row: (row["mean_rtf"], row["wer_delta_estimate"]))[0]
    return {
        "status": "selected",
        "quant": selected["quant"],
        "artifact_path": selected["artifact_path"],
        "mean_rtf": selected["mean_rtf"],
        "wer_delta_estimate": selected["wer_delta_estimate"],
        "reason": "Fastest candidate under RTF and WER thresholds.",
    }


def write_experiment_csv(experiments: list[dict[str, Any]], path: Path) -> None:
    keys = [
        "quant",
        "artifact_path",
        "artifact_exists",
        "status",
        "mean_rtf",
        "p95_rtf",
        "mean_wall_rtf",
        "ram_slope_mb_per_loop",
        "wer_delta_estimate",
        "rtf_pass",
        "load_once_pass",
        "memory_leak_pass_simple",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in experiments:
            writer.writerow({key: row.get(key, "") for key in keys})


if __name__ == "__main__":
    main()
