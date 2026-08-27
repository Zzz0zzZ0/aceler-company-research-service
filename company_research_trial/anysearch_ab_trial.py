#!/usr/bin/env python3
"""Five-company timing trial: Hermes web baseline vs AnySearch evidence prefetch."""

from __future__ import annotations

import concurrent.futures
import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_research_trial.company_research_trial import (
    ANYSEARCH_CLI,
    DEFAULT_HERMES,
    DEFAULT_OUTPUT_ROOT,
    anysearch_pack,
    hostname,
    load_env_file,
    research_one,
    run_anysearch_cli,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
BASELINE_RUN = DEFAULT_OUTPUT_ROOT / "20260814T062747Z"
SAMPLE_INDICES = (2, 6, 7, 14, 17)


def baseline_items() -> dict[int, dict[str, Any]]:
    items: dict[int, dict[str, Any]] = {}
    for path in (BASELINE_RUN / "records").glob("*/result.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("index") in SAMPLE_INDICES:
            items[item["index"]] = item
    missing = set(SAMPLE_INDICES) - set(items)
    if missing:
        raise RuntimeError(f"Missing baseline indices: {sorted(missing)}")
    return items


run_cli = run_anysearch_cli


def run_company(
    baseline: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    index = baseline["index"]
    record = baseline["record"]
    company_dir = run_dir / "records" / f"{index:03d}-{record['id'][:8]}"
    company_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    pack, search_meta = anysearch_pack(record)
    (company_dir / "anysearch-evidence.md").write_text(pack, encoding="utf-8")
    (company_dir / "anysearch-meta.json").write_text(
        json.dumps(search_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    item = research_one(
        record,
        index,
        run_dir,
        DEFAULT_HERMES,
        timeout=600,
        reasoning="medium",
        evidence_pack=pack,
        toolsets="skills,terminal,file",
        use_anysearch=False,
    )
    item.update(
        {
            "anysearch": search_meta,
            "hermes_seconds": item["duration_seconds"],
            "total_seconds": round(time.monotonic() - started, 1),
            "baseline_seconds": baseline["duration_seconds"],
            "baseline_score": baseline["validation"].get("score"),
            "baseline_sources": len((baseline.get("assessment") or {}).get("sources") or []),
        }
    )
    Path(item["record_dir"], "result.json").write_text(
        json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return item


def write_report(run_dir: Path, items: list[dict[str, Any]]) -> None:
    valid_items = [item for item in items if item["status"] == "valid"]
    baseline_average = sum(item["baseline_seconds"] for item in items) / len(items)
    new_average = sum(item["total_seconds"] for item in items) / len(items)
    rows = []
    markdown_rows = []
    for item in items:
        assessment = item.get("assessment") or {}
        validation = item.get("validation") or {}
        source_count = len(assessment.get("sources") or [])
        saved = item["baseline_seconds"] - item["total_seconds"]
        markdown_rows.append(
            f"| {item['record']['name']} | {item['baseline_seconds']:.1f}s | {item['anysearch']['seconds']:.1f}s | "
            f"{item['hermes_seconds']:.1f}s | {item['total_seconds']:.1f}s | {saved:+.1f}s | "
            f"{item['baseline_score']}% → {validation.get('score', '—')}% | {item['baseline_sources']} → {source_count} | {item['status']} |"
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['record']['name'])}</td><td>{item['baseline_seconds']:.1f}s</td>"
            f"<td>{item['anysearch']['seconds']:.1f}s</td><td>{item['hermes_seconds']:.1f}s</td>"
            f"<td>{item['total_seconds']:.1f}s</td><td>{saved:+.1f}s</td>"
            f"<td>{item['baseline_score']}% → {validation.get('score', '—')}%</td>"
            f"<td>{item['baseline_sources']} → {source_count}</td><td>{html.escape(item['status'])}</td></tr>"
        )
    speedup = baseline_average / new_average if new_average else 0
    measurement_notes = [item["measurement_note"] for item in items if item.get("measurement_note")]
    summary = {
        "sample_count": len(items),
        "valid": len(valid_items),
        "baseline_average_seconds": round(baseline_average, 1),
        "anysearch_average_seconds": round(new_average, 1),
        "speedup_ratio": round(speedup, 2),
        "average_saved_seconds": round(baseline_average - new_average, 1),
        "observable_anysearch_batch_calls": sum(item["anysearch"]["batch_calls"] for item in items),
        "observable_anysearch_extract_calls": sum(item["anysearch"]["extract_calls"] for item in items),
        "measurement_notes": measurement_notes,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "comparison.md").write_text(
        "# AnySearch 预取证据 A/B 试验\n\n"
        f"- 样本：{len(items)} 家；有效：{len(valid_items)}\n"
        f"- 原生 web 平均：{baseline_average:.1f}s\n"
        f"- AnySearch + Hermes 平均：{new_average:.1f}s\n"
        f"- 速度比：{speedup:.2f}x\n\n"
        "| 公司 | 原生 web | AnySearch | Hermes | B组总计 | 节省 | 评分 | 来源数 | 状态 |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---|\n"
        + "\n".join(markdown_rows)
        + "\n\n> 注意：A 组复用历史运行，样本较小且个别记录包含校验重试；结果用于判断方向，不是严格基准测试。\n"
        + "".join(f"> {note}\n" for note in measurement_notes),
        encoding="utf-8",
    )
    (run_dir / "comparison.html").write_text(
        "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AnySearch A/B</title><style>body{font:15px/1.6 -apple-system,sans-serif;max-width:1300px;margin:32px auto;padding:0 20px;color:#172033}"
        "table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #dbe3ec;text-align:left}th{background:#eef3f8}.wrap{overflow:auto;border:1px solid #dbe3ec;border-radius:10px}"
        ".metric{display:inline-block;padding:10px 14px;margin:0 8px 16px 0;background:#f3f6fa;border-radius:8px;font-weight:650}</style>"
        "<h1>AnySearch 预取证据 A/B 试验</h1>"
        f"<div class='metric'>原生 web 平均 {baseline_average:.1f}s</div><div class='metric'>AnySearch + Hermes 平均 {new_average:.1f}s</div>"
        f"<div class='metric'>速度比 {speedup:.2f}x</div><div class='metric'>有效 {len(valid_items)}/{len(items)}</div>"
        "<div class='wrap'><table><thead><tr><th>公司</th><th>原生 web</th><th>AnySearch</th><th>Hermes</th><th>B组总计</th><th>节省</th><th>评分</th><th>来源数</th><th>状态</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div><p>注意：A 组复用历史运行，个别记录包含校验重试；本试验用于判断方向。</p>"
        + "".join(f"<p>{html.escape(note)}</p>" for note in measurement_notes),
        encoding="utf-8",
    )


def main() -> int:
    load_env_file(PROJECT_DIR / "config" / "local.env")
    if not ANYSEARCH_CLI.is_file():
        raise RuntimeError(f"AnySearch CLI unavailable: {ANYSEARCH_CLI}")
    baselines = baseline_items()
    run_dir = DEFAULT_OUTPUT_ROOT / "anysearch-ab" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True)
    print(json.dumps({"run_dir": str(run_dir), "sample_indices": SAMPLE_INDICES}), flush=True)
    items: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(run_company, baselines[index], run_dir): index for index in SAMPLE_INDICES}
        for future in concurrent.futures.as_completed(futures):
            item = future.result()
            items.append(item)
            print(
                json.dumps(
                    {
                        "company": item["record"]["name"],
                        "status": item["status"],
                        "anysearch_seconds": item["anysearch"]["seconds"],
                        "hermes_seconds": item["hermes_seconds"],
                        "total_seconds": item["total_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    items.sort(key=lambda item: item["index"])
    write_report(run_dir, items)
    print((run_dir / "summary.json").read_text(encoding="utf-8"), flush=True)
    return 0 if all(item["status"] == "valid" for item in items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
