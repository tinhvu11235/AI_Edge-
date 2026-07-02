#!/usr/bin/env python3
import json
import math
import sys
from pathlib import Path


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_rows(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize(path):
    rows = load_rows(path)
    ttft = [r["ttft_max_ms"] for r in rows if r.get("ttft_max_ms", -1) >= 0]
    barge = [
        r["barge_in_reaction_ms"]
        for r in rows
        if r.get("barge_in_reaction_ms", -1) >= 0
    ]
    underruns = sum(int(r.get("underruns", 0)) for r in rows)
    return {
        "file": str(path),
        "count": len(rows),
        "ttft_p50_ms": percentile(ttft, 0.50),
        "ttft_p95_ms": percentile(ttft, 0.95),
        "ttft_p99_ms": percentile(ttft, 0.99),
        "ttft_worst_ms": max(ttft) if ttft else None,
        "barge_p95_ms": percentile(barge, 0.95),
        "barge_worst_ms": max(barge) if barge else None,
        "underruns": underruns,
    }


def main(argv):
    if len(argv) < 2:
        print("Usage: summarize_benchmark.py FILE.jsonl [FILE.jsonl ...]", file=sys.stderr)
        return 2
    for filename in argv[1:]:
        print(json.dumps(summarize(filename), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
