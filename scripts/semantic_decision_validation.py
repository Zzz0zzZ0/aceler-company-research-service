#!/usr/bin/env python3
"""Run the current decision graph against saved evidence and CRM labels."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from company_research_trial.company_research_trial import DEFAULT_HERMES, load_env_file, research_one  # noqa: E402


DEFAULT_SOURCE = ROOT / "outputs" / "relevance-rerank-validation" / "20260904T033233Z"
DEFAULT_LABELS = ROOT / "outputs" / "semantic-decision-validation" / "20260904T085617Z-full100-repeat" / "summary.json"
OUTPUT_ROOT = ROOT / "outputs" / "semantic-decision-validation"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return sorted(values)[min(len(values) - 1, int(len(values) * fraction))]


def prompt_sizes(item: dict[str, Any]) -> dict[str, list[int]]:
    research = item.get("research") or {}
    values: dict[str, list[int]] = {role: [] for role in ("evidence", "catalog_router", "lead", "recall", "arbiter")}
    for role, key in (("evidence", "evidence_agent"), ("catalog_router", "catalog_router")):
        size = (research.get(key) or {}).get("input_chars")
        if isinstance(size, int):
            values[role].append(size)
    for attempt in research.get("attempts") or []:
        role = attempt.get("role") or ("arbiter" if attempt.get("kind") == "arbiter" else None)
        size = attempt.get("input_chars")
        if role in values and isinstance(size, int):
            values[role].append(size)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--tag", default="multi-agent-v2")
    args = parser.parse_args()
    load_env_file(ROOT / "config" / "local.env")

    records = json.loads((args.source / "input-records.json").read_text(encoding="utf-8"))[: args.limit]
    label_rows = {
        row["index"]: row["manual"]
        for row in json.loads(args.labels.read_text(encoding="utf-8"))["rows"]
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = OUTPUT_ROOT / f"{stamp}-{args.tag}"
    run_dir.mkdir(parents=True)
    started = time.monotonic()

    def run(index: int, record: dict[str, Any]) -> dict[str, Any]:
        evidence = (args.source / "records" / f"{index:03d}" / "structured-evidence.md").read_text(encoding="utf-8")
        return research_one(
            record,
            index,
            run_dir,
            hermes=DEFAULT_HERMES,
            evidence_pack=evidence,
            use_anysearch=False,
            max_attempts=3,
        )

    results: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run, index, record): index for index, record in enumerate(records, 1)}
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = {"index": index, "status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}
            print(f"[{completed}/{len(futures)}] {index:03d} {results[index].get('status')}", flush=True)

    rows: list[dict[str, Any]] = []
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "unscorable_positive": 0, "unscorable_negative": 0}
    all_sizes = {role: [] for role in ("evidence", "catalog_router", "lead", "recall", "arbiter")}
    for index, record in enumerate(records, 1):
        item = results[index]
        manual = label_rows[index]
        expected = manual["follow_up"] == "跟进"
        valid = item.get("status") == "valid"
        assessment = item.get("assessment") or {}
        match = assessment.get("match") or {}
        predicted = match.get("follow_up") == "跟进"
        if not valid:
            counts["unscorable_positive" if expected else "unscorable_negative"] += 1
        elif expected and predicted:
            counts["tp"] += 1
        elif expected:
            counts["fn"] += 1
        elif predicted:
            counts["fp"] += 1
        else:
            counts["tn"] += 1
        sizes = prompt_sizes(item)
        for role, values in sizes.items():
            all_sizes[role].extend(values)
        research = item.get("research") or {}
        rows.append(
            {
                "index": index,
                "name": record.get("name"),
                "manual": manual,
                "status": item.get("status"),
                "score": (item.get("validation") or {}).get("score"),
                "product_match": match.get("product_match"),
                "commercial_match": match.get("commercial_match"),
                "follow_up": match.get("follow_up"),
                "selected_role": research.get("selected_role"),
                "agent_calls": research.get("agent_call_count", 0),
                "role_call_counts": research.get("role_call_counts", {}),
                "router_products": (research.get("catalog_router") or {}).get("products", []),
                "prompt_chars": sizes,
                "duration_seconds": item.get("duration_seconds"),
                "errors": item.get("errors", []),
                "record_dir": item.get("record_dir"),
            }
        )

    tp, fp, tn, fn = (counts[key] for key in ("tp", "fp", "tn", "fn"))
    positive_total = tp + fn + counts["unscorable_positive"]
    recall = tp / positive_total if positive_total else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    latencies = [float(row["duration_seconds"]) for row in rows if isinstance(row.get("duration_seconds"), (int, float))]
    prompt_summary = {
        role: {
            "calls": len(values),
            "median": round(statistics.median(values), 1) if values else 0,
            "p95": percentile(values, 0.95),
            "max": max(values) if values else 0,
        }
        for role, values in all_sizes.items()
    }
    summary = {
        "run_dir": str(run_dir),
        "source_run": str(args.source),
        "companies": len(records),
        "workers": args.workers,
        "model": "MiniMax-M3 via Hermes",
        "anysearch_calls": 0,
        "wall_seconds": round(time.monotonic() - started, 1),
        "metrics": {
            **counts,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "accuracy": round((tp + tn) / len(records), 4),
        },
        "valid": sum(row["status"] == "valid" for row in rows),
        "agent_calls": sum(int(row["agent_calls"] or 0) for row in rows),
        "recall_triggered": sum((results[i].get("research") or {}).get("zero_score_review", {}).get("triggered") is True for i in results),
        "recall_selected": sum(row["selected_role"] == "recall" for row in rows),
        "prompt_chars": prompt_summary,
        "latency_seconds": {
            "mean": round(statistics.mean(latencies), 1) if latencies else 0,
            "median": round(statistics.median(latencies), 1) if latencies else 0,
            "p95": percentile(latencies, 0.95),
            "max": max(latencies) if latencies else 0,
        },
        "rows": rows,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = (
        "# 多 Agent v2 语义验证\n\n"
        f"- 样本：{len(records)} 家；并发：{args.workers}；AnySearch：0 次\n"
        f"- 召回率：{recall:.2%}；精确率：{precision:.2%}\n"
        f"- TP/FP/TN/FN：{tp}/{fp}/{tn}/{fn}；不可评分：{counts['unscorable_positive'] + counts['unscorable_negative']}\n"
        f"- Agent 调用：{summary['agent_calls']}；墙钟时间：{summary['wall_seconds']} 秒\n"
        f"- Prompt 字符统计：`{json.dumps(prompt_summary, ensure_ascii=False)}`\n"
    )
    (run_dir / "验证报告.md").write_text(report, encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "metrics": summary["metrics"]}, ensure_ascii=False))
    return 0 if recall > 0.8 and precision >= 0.75 else 2


if __name__ == "__main__":
    raise SystemExit(main())
