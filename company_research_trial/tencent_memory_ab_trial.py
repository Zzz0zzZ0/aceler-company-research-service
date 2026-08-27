#!/usr/bin/env python3
"""Five-company frozen-evidence A/B arm for TencentDB Agent Memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from company_research_trial import (
    load_env_file,
    research_one,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_RUN = PROJECT_DIR / "outputs/company-research-trial/20260821T090613Z-m3-frozen-20"
SAMPLE_INDICES = (4, 5, 6, 14, 18)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("baseline", "tencent-memory"), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--hermes",
        type=Path,
        default=Path.home() / ".local/bin/tencent-memory-test",
    )
    args = parser.parse_args()

    load_env_file(PROJECT_DIR / "config/local.env")
    selected = json.loads((SOURCE_RUN / "selected-companies.json").read_text(encoding="utf-8"))
    args.run_dir = args.run_dir.resolve()
    args.run_dir.mkdir(parents=True, exist_ok=False)

    records = []
    for source_index in SAMPLE_INDICES:
        record = selected[source_index - 1]
        source_dir = next((SOURCE_RUN / "records").glob(f"{source_index:03d}-*"))
        evidence = (source_dir / "anysearch-evidence.md").read_text(encoding="utf-8")
        result = research_one(
            record,
            source_index,
            args.run_dir,
            hermes=args.hermes,
            timeout=360,
            reasoning="medium",
            evidence_pack=evidence,
            toolsets="context_engine",
            use_anysearch=False,
            max_attempts=1,
            review_zero_score=False,
        )
        records.append(result)
        print(
            json.dumps(
                {
                    "arm": args.arm,
                    "index": source_index,
                    "company": record["name"],
                    "status": result["status"],
                    "seconds": result["duration_seconds"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        "arm": args.arm,
        "source_run": str(SOURCE_RUN),
        "sample_indices": list(SAMPLE_INDICES),
        "anysearch_calls": 0,
        "valid": sum(item["status"] == "valid" for item in records),
        "failed": sum(item["status"] != "valid" for item in records),
        "results": [
            {
                "index": item["index"],
                "company": item["record"]["name"],
                "status": item["status"],
                "duration_seconds": item["duration_seconds"],
                "record_dir": item["record_dir"],
            }
            for item in records
        ],
    }
    (args.run_dir / "arm-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
