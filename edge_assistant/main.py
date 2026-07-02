from __future__ import annotations

import argparse
import json

from .config import load_config
from .pipeline import AlwaysOnPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI Edge assistant pipeline")
    parser.add_argument("--config", default="configs/pipeline.sim.toml")
    parser.add_argument("--mode", choices=["background", "active"], default="active")
    parser.add_argument("--duration", type=float, default=60.0)
    args = parser.parse_args()

    config = load_config(args.config)
    stats = AlwaysOnPipeline(config, mode=args.mode).run(args.duration)
    print(json.dumps(stats.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
