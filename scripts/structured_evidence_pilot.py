#!/usr/bin/env python3
"""Compare the existing flow with a two-pass, quote-verified evidence flow."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from company_research_trial.company_research_trial import (  # noqa: E402
    ANYSEARCH_CACHE_DIR,
    DEFAULT_HERMES,
    _invoke_hermes,
    agentic_anysearch_pack,
    anysearch_pack,
    recall_first_anysearch_pack,
    load_env_file,
    research_one,
)
from company_research_trial.structured_evidence import extraction_prompt, prepare_structured_evidence  # noqa: E402


SOURCE_RUN = ROOT / "outputs" / "company-research-trial" / "20260901T014301Z-file-n100"
OUTPUT_ROOT = ROOT / "outputs" / "structured-evidence-pilot"
INDICES = (2, 30, 39, 45, 57, 62, 63, 82, 87, 97, 3, 8, 9, 17, 25, 36, 50, 55, 56, 80)
POSITIVE = {2, 30, 39, 45, 57, 62, 63, 82, 87, 97}
NEGATIVE = {3, 8, 9, 17, 25, 36, 50, 55, 56}
WORKERS = 3
THRESHOLD = 55


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_record(index: int) -> tuple[dict[str, Any], int | None, Path | None]:
    result_path = next(iter(SOURCE_RUN.glob(f"records/{index:03d}-*/result.json")), None)
    if result_path is None:
        raise FileNotFoundError(f"source result missing for index {index}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    score = result.get("validation", {}).get("score") if result.get("status") == "valid" else None
    evidence_path = result_path.parent / "anysearch-evidence.md"
    return result["record"], score, evidence_path if evidence_path.is_file() else None


def _crm_markdown_records(path: Path) -> dict[int, dict[str, Any]]:
    """Read identity seeds from the seven-column CRM Markdown table."""
    records: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        columns = [value.strip().replace("**", "") for value in line.strip().strip("|").split("|")]
        if len(columns) != 7:
            raise ValueError(f"CRM row must contain seven columns: {line[:120]}")
        index = int(columns[0])
        url_match = re.search(r"\((https?://[^)]+)\)", columns[5])
        record = {
            "id": f"crm-{index:03d}",
            "name": columns[4],
            "country": columns[6],
        }
        if url_match:
            record["website"] = url_match.group(1)
        records[index] = record
    if not records or sorted(records) != list(range(1, len(records) + 1)):
        raise ValueError("CRM Markdown must contain consecutively numbered company rows starting at 1")
    return records


def _label(index: int) -> str:
    return "positive" if index in POSITIVE else "negative" if index in NEGATIVE else "middle"


def run_company(
    index: int,
    run_dir: Path,
    refresh_evidence: bool = False,
    agentic_retrieval: bool = False,
    reuse_evidence_cache: bool = False,
    input_records: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if input_records is None:
        record, baseline_score, evidence_path = _source_record(index)
    else:
        record, baseline_score, evidence_path = input_records[index], None, None
    record_dir = run_dir / "records" / f"{index:03d}"
    record_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "index": index,
        "name": str(record.get("name") or ""),
        "label": _label(index),
        "baseline_score": baseline_score,
        "candidate_score": None,
    }
    search_meta: dict[str, Any] | None = None
    if refresh_evidence or agentic_retrieval or reuse_evidence_cache:
        try:
            if agentic_retrieval:
                evidence_pack, search_meta = agentic_anysearch_pack(
                    record, record_dir, hermes=DEFAULT_HERMES
                )
            elif refresh_evidence:
                evidence_pack, search_meta = recall_first_anysearch_pack(
                    record,
                    record_dir,
                    hermes=DEFAULT_HERMES,
                    cache_dir=ANYSEARCH_CACHE_DIR,
                    refresh_cache=True,
                )
            else:
                evidence_pack, search_meta = anysearch_pack(
                    record,
                    cache_dir=ANYSEARCH_CACHE_DIR,
                )
            (record_dir / "anysearch-evidence.md").write_text(evidence_pack, encoding="utf-8")
            _write_json(record_dir / "anysearch-meta.json", search_meta)
        except Exception as exc:
            item = {**base, "candidate_status": "unscorable", "error": str(exc)}
            _write_json(record_dir / "result.json", item)
            return item
    elif evidence_path is None:
        item = {**base, "candidate_status": "unscorable", "error": "frozen evidence is missing"}
        _write_json(record_dir / "result.json", item)
        return item
    else:
        evidence_pack = evidence_path.read_text(encoding="utf-8")
    extraction: dict[str, Any] | None = None
    extraction_errors: list[str] = []
    for attempt in range(1, 3):
        invocation = _invoke_hermes(
            record_dir=record_dir,
            hermes=DEFAULT_HERMES,
            timeout=300,
            reasoning="medium",
            prompt=extraction_prompt(base["name"], evidence_pack),
            usage_path=record_dir / f"structure-usage-attempt-{attempt}.json",
            raw_path=record_dir / f"structure-raw-attempt-{attempt}.txt",
            attempt_kind=f"structure_attempt_{attempt}",
        )
        extraction_errors.extend(str(error) for error in invocation.get("errors") or [])
        if isinstance(invocation.get("assessment"), dict):
            extraction = invocation["assessment"]
            break
    if extraction is None:
        item = {**base, "candidate_status": "unscorable", "errors": extraction_errors}
        _write_json(record_dir / "result.json", item)
        return item

    structured = prepare_structured_evidence(extraction, evidence_pack)
    _write_json(record_dir / "structured-evidence.json", structured)
    if structured["status"] != "usable":
        item = {**base, "candidate_status": "unscorable", "structure": structured}
        _write_json(record_dir / "result.json", item)
        return item
    (record_dir / "structured-evidence.md").write_text(structured["evidence_pack"], encoding="utf-8")

    scored = research_one(
        record,
        index,
        run_dir / "scoring",
        evidence_pack=structured["evidence_pack"],
        use_anysearch=False,
        max_attempts=2,
        review_zero_score=True,
    )
    candidate_score = scored.get("validation", {}).get("score") if scored.get("status") == "valid" else None
    item = {
        **base,
        "candidate_score": candidate_score,
        "candidate_status": scored.get("status") if candidate_score is not None else "unscorable",
        "structure": {key: value for key, value in structured.items() if key != "evidence_pack"},
        "anysearch": search_meta,
        "scoring_result": scored.get("record_dir"),
    }
    _write_json(record_dir / "result.json", item)
    return item


def run_company_resilient(
    index: int,
    run_dir: Path,
    refresh_evidence: bool = False,
    agentic_retrieval: bool = False,
    reuse_evidence_cache: bool = False,
    input_records: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep a batch moving when one company's unexpected data breaks a stage."""
    try:
        return run_company(
            index,
            run_dir,
            refresh_evidence,
            agentic_retrieval,
            reuse_evidence_cache,
            input_records,
        )
    except Exception as exc:
        try:
            if input_records is None:
                record, baseline_score, _ = _source_record(index)
            else:
                record, baseline_score = input_records[index], None
            name = str(record.get("name") or "")
        except Exception:
            baseline_score, name = None, ""
        record_dir = run_dir / "records" / f"{index:03d}"
        record_dir.mkdir(parents=True, exist_ok=True)
        item = {
            "index": index,
            "name": name,
            "label": _label(index),
            "baseline_score": baseline_score,
            "candidate_score": None,
            "candidate_status": "unscorable",
            "error": f"unexpected pipeline error: {type(exc).__name__}: {str(exc)[:500]}",
        }
        _write_json(record_dir / "result.json", item)
        return item


def _metrics(items: list[dict[str, Any]], score_key: str) -> dict[str, int]:
    positives = [item for item in items if item["label"] == "positive"]
    negatives = [item for item in items if item["label"] == "negative"]
    return {
        "true_positives": sum((item.get(score_key) or 0) >= THRESHOLD for item in positives),
        "false_positives": sum((item.get(score_key) or 0) >= THRESHOLD for item in negatives),
        "positive_zero_scores": sum(item.get(score_key) == 0 for item in positives),
        "positive_unscorable": sum(item.get(score_key) is None for item in positives),
        "negative_scored": sum(item.get(score_key) is not None for item in negatives),
        "total_unscorable": sum(item.get(score_key) is None for item in items),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-evidence", action="store_true", help="Run live AnySearch retrieval before extraction")
    parser.add_argument(
        "--agentic-retrieval",
        action="store_true",
        help="Let Hermes plan and select live AnySearch evidence before quote verification",
    )
    parser.add_argument(
        "--reuse-evidence-cache",
        action="store_true",
        help="Reuse a fresh cached AnySearch evidence pack, fetching and caching it on a miss",
    )
    parser.add_argument("--workers", type=int, default=WORKERS, help="Maximum concurrent companies")
    parser.add_argument("--indices", nargs="*", type=int, help="Optional subset of the fixed validation indices")
    parser.add_argument("--crm-markdown", type=Path, help="Run identity seeds from a seven-column CRM Markdown table")
    parser.add_argument(
        "--resume-run-dir",
        type=Path,
        help="Continue an existing run, skipping indices that already have a readable result.json",
    )
    parser.add_argument(
        "--retry-unscorable",
        action="store_true",
        help="With --resume-run-dir, rerun completed items whose candidate score is unavailable",
    )
    args = parser.parse_args()
    input_records = _crm_markdown_records(args.crm_markdown.resolve()) if args.crm_markdown else None
    indices = tuple(args.indices) if args.indices else tuple(input_records) if input_records else INDICES
    load_env_file(ROOT / "config" / "local.env")
    live_evidence = args.refresh_evidence or args.agentic_retrieval or args.reuse_evidence_cache
    output_root = ROOT / "outputs" / ("relevance-rerank-validation" if live_evidence else OUTPUT_ROOT.name)
    run_dir = args.resume_run_dir.resolve() if args.resume_run_dir else (
        output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    if args.resume_run_dir and not run_dir.is_dir():
        parser.error(f"resume run directory does not exist: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=bool(args.resume_run_dir))
    if input_records is not None:
        _write_json(run_dir / "input-records.json", [input_records[index] for index in indices])
    started = time.monotonic()
    completed: dict[int, dict[str, Any]] = {}
    for index in indices:
        result_path = run_dir / "records" / f"{index:03d}" / "result.json"
        if not result_path.is_file():
            continue
        try:
            item = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(item, dict) and not (args.retry_unscorable and item.get("candidate_score") is None):
            completed[index] = item
    pending = tuple(index for index in indices if index not in completed)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        fresh_items = list(
            pool.map(
                lambda index: run_company_resilient(
                    index,
                    run_dir,
                    args.refresh_evidence,
                    args.agentic_retrieval,
                    args.reuse_evidence_cache,
                    input_records,
                ),
                pending,
            )
        )
    completed.update({int(item["index"]): item for item in fresh_items})
    items = [completed[index] for index in indices]
    baseline = _metrics(items, "baseline_score")
    candidate = _metrics(items, "candidate_score")
    target_met = (
        candidate["true_positives"] >= 8
        and candidate["false_positives"] == 0
        and candidate["positive_zero_scores"] == 0
        and candidate["positive_unscorable"] <= 1
        and candidate["negative_scored"] >= 6
    )
    elapsed_seconds = time.monotonic() - started
    if args.resume_run_dir:
        result_paths = list(run_dir.glob("records/*/result.json"))
        if result_paths:
            created_at = getattr(run_dir.stat(), "st_birthtime", run_dir.stat().st_mtime)
            elapsed_seconds = max(path.stat().st_mtime for path in result_paths) - created_at
    summary = {
        "run_dir": str(run_dir),
        "source_file": str(args.crm_markdown.resolve()) if args.crm_markdown else str(SOURCE_RUN),
        "companies": len(items),
        "workers": args.workers,
        "evidence_mode": (
            "live_agentic"
            if args.agentic_retrieval
            else "live_reranked"
            if args.refresh_evidence
            else "cached_reranked"
            if args.reuse_evidence_cache
            else "frozen"
        ),
        "threshold": THRESHOLD,
        "seconds": round(max(0.0, elapsed_seconds), 1),
        "resumed": bool(args.resume_run_dir),
        "skipped_completed": len(indices) - len(pending),
        "baseline": baseline,
        "candidate": candidate,
        "target_met": target_met,
        "items": items,
    }
    _write_json(run_dir / "summary.json", summary)
    print(json.dumps({key: value for key, value in summary.items() if key != "items"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
