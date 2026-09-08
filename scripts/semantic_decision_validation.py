#!/usr/bin/env python3
"""Run the current decision graph against saved evidence and CRM labels."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
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


def crm_markdown_dataset(path: Path) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Read seven/eight-column CRM tables, preserving Markdown link targets."""
    records: list[dict[str, Any]] = []
    labels: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        row = line.replace("\\|", "__PIPE__").strip()[1:]
        if row.endswith("|"):
            row = row[:-1]
        columns = [value.strip().replace("**", "") for value in row.split("|")]
        columns = [value.replace("__PIPE__", "|") for value in columns]
        if len(columns) not in {7, 8}:
            raise ValueError(f"CRM row must contain seven or eight columns: {line[:120]}")
        index = int(columns[0])
        target = re.fullmatch(r"\[[^\]]*\]\(<?(https?://[^\s<>]+)>?\)", columns[5])
        url = re.search(r"https?://[^\s<>]+", target.group(1) if target else columns[5])
        record = {"id": f"crm-{index:03d}", "name": columns[4], "country": columns[6]}
        if url:
            record["website"] = url.group(0)
        records.append(record)
        labels[index] = {
            "product_match": int(columns[1]),
            "commercial_match": int(columns[2]),
            "follow_up": columns[3],
        }
    if not records or [int(record["id"].split("-")[1]) for record in records] != list(range(1, len(records) + 1)):
        raise ValueError("CRM Markdown must contain consecutively numbered rows starting at 1")
    return records, labels


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
    parser.add_argument("--crm-markdown", type=Path, help="Run live research from a seven/eight-column CRM Markdown test set")
    parser.add_argument("--refresh-evidence-cache", action="store_true")
    parser.add_argument("--resume-run-dir", type=Path, help="Reuse valid results and rerun only failed or missing companies")
    args = parser.parse_args()
    load_env_file(ROOT / "config" / "local.env")

    if args.crm_markdown:
        records, label_rows = crm_markdown_dataset(args.crm_markdown.resolve())
        records = records[: args.limit]
    else:
        records = json.loads((args.source / "input-records.json").read_text(encoding="utf-8"))[: args.limit]
        label_rows = {
            row["index"]: row["manual"]
            for row in json.loads(args.labels.read_text(encoding="utf-8"))["rows"]
        }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.resume_run_dir.resolve() if args.resume_run_dir else OUTPUT_ROOT / f"{stamp}-{args.tag}"
    run_dir.mkdir(parents=True, exist_ok=bool(args.resume_run_dir))
    (run_dir / "input-records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()

    def run(index: int, record: dict[str, Any]) -> dict[str, Any]:
        evidence = None
        if not args.crm_markdown:
            evidence = (args.source / "records" / f"{index:03d}" / "structured-evidence.md").read_text(encoding="utf-8")
        return research_one(
            record,
            index,
            run_dir,
            hermes=DEFAULT_HERMES,
            evidence_pack=evidence,
            use_anysearch=bool(args.crm_markdown),
            max_attempts=3,
            refresh_evidence_cache=args.refresh_evidence_cache,
        )

    results: dict[int, dict[str, Any]] = {}
    if args.resume_run_dir:
        for index, record in enumerate(records, 1):
            result_path = run_dir / "records" / f"{index:03d}-{record['id']}" / "result.json"
            if result_path.is_file():
                try:
                    item = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if item.get("status") == "valid":
                    results[index] = item
    pending = [(index, record) for index, record in enumerate(records, 1) if index not in results]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run, index, record): index for index, record in pending}
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
                "retrieval_agent_calls": len(list((run_dir / "records" / f"{index:03d}-{record['id']}").glob("agentic-*-raw.txt"))),
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
    wall_seconds = time.monotonic() - started
    if args.resume_run_dir:
        result_paths = list(run_dir.glob("records/*/result.json"))
        if result_paths:
            created_at = getattr(run_dir.stat(), "st_birthtime", run_dir.stat().st_mtime)
            wall_seconds = max(path.stat().st_mtime for path in result_paths) - created_at
    anysearch_calls = sum(
        int((item.get("anysearch") or {}).get("search_calls") or 0)
        + int((item.get("anysearch") or {}).get("extract_calls") or 0)
        for item in results.values()
    )
    summary = {
        "run_dir": str(run_dir),
        "source_run": str(args.crm_markdown.resolve() if args.crm_markdown else args.source),
        "companies": len(records),
        "workers": args.workers,
        "model": os.getenv("ACELER_HERMES_MODEL", "MiniMax-M3"),
        "provider": os.getenv("ACELER_HERMES_PROVIDER", "minimax-cn"),
        "evidence_mode": "live" if args.crm_markdown else "saved_structured",
        "anysearch_calls": anysearch_calls,
        "wall_seconds": round(max(0.0, wall_seconds), 1),
        "resumed": bool(args.resume_run_dir),
        "skipped_valid": len(records) - len(pending),
        "metrics": {
            **counts,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "accuracy": round((tp + tn) / len(records), 4),
        },
        "valid": sum(row["status"] == "valid" for row in rows),
        "agent_calls": sum(int(row["agent_calls"] or 0) for row in rows),
        "retrieval_agent_calls": sum(row["retrieval_agent_calls"] for row in rows),
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
        f"- 样本：{len(records)} 家；并发：{args.workers}；AnySearch：{anysearch_calls} 次\n"
        f"- 召回率：{recall:.2%}；精确率：{precision:.2%}\n"
        f"- TP/FP/TN/FN：{tp}/{fp}/{tn}/{fn}；不可评分：{counts['unscorable_positive'] + counts['unscorable_negative']}\n"
        f"- 决策 Agent 调用：{summary['agent_calls']}；检索 Agent 调用：{summary['retrieval_agent_calls']}；墙钟时间：{summary['wall_seconds']} 秒\n"
        f"- Prompt 字符统计：`{json.dumps(prompt_summary, ensure_ascii=False)}`\n"
    )
    (run_dir / "验证报告.md").write_text(report, encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "metrics": summary["metrics"]}, ensure_ascii=False))
    return 0 if recall > 0.8 and precision >= 0.75 else 2


if __name__ == "__main__":
    raise SystemExit(main())
