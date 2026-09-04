#!/usr/bin/env python3
"""Merge the 20+80 live runs and compare them with the 100-company manual set."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path
from urllib.parse import urlparse


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manual_rows(path: Path) -> dict[int, dict]:
    text = path.read_text(encoding="utf-8")
    headings = list(re.finditer(r"(?m)^#{1,3}\s+(\d+)\.\s+(.+?)\s*$", text))
    rows: dict[int, dict] = {}
    for position, heading in enumerate(headings):
        block = text[heading.end() : headings[position + 1].start() if position + 1 < len(headings) else len(text)]
        match = re.search(r"匹配度[:：]\s*\*{0,2}([0-9]+(?:\.[0-9]+)?)/10(?:\.0)?", block)
        if not match:
            raise ValueError(f"manual score missing for index {heading.group(1)}")
        index = int(heading.group(1))
        rows[index] = {
            "index": index,
            "manual_name": heading.group(2).strip(),
            "manual_score": round(float(match.group(1)) * 10),
        }
    if set(rows) != set(range(1, 101)):
        raise ValueError("manual set must contain exactly indices 1..100")
    return rows


def run_items(run: Path) -> dict[int, dict]:
    summary = read_json(run / "summary.json")
    return {int(item["index"]): item for item in summary["items"]}


def source_result(source_run: Path, index: int) -> dict:
    matches = list(source_run.glob(f"records/{index:03d}-*/result.json"))
    if len(matches) != 1:
        raise ValueError(f"expected one source result for {index}, got {len(matches)}")
    return read_json(matches[0])


def assessment_fields(item: dict) -> dict:
    directory = item.get("scoring_result")
    if not directory:
        return {}
    path = Path(directory) / "accepted-assessment.json"
    if not path.is_file():
        return {}
    assessment = read_json(path)
    role = assessment.get("role_judgment") or {}
    sources = assessment.get("sources") or []
    return {
        "operational_role": role.get("operational_role"),
        "commercial_relationship": role.get("commercial_relationship"),
        "confidence": (assessment.get("match") or {}).get("confidence"),
        "entry_barrier": (assessment.get("match") or {}).get("entry_barrier"),
        "source_urls": [source.get("url") for source in sources if isinstance(source, dict) and source.get("url")],
    }


def failure_stage(item: dict) -> str:
    if item.get("candidate_score") is not None:
        return ""
    if "AnySearch" in str(item.get("error") or ""):
        return "retrieval"
    structure = item.get("structure") or {}
    if structure and structure.get("status") != "usable":
        return "structured_extraction"
    return "scoring"


def confusion(rows: list[dict], score_key: str, threshold: int) -> dict:
    tp = fp = tn = fn = abstain_positive = abstain_negative = 0
    for row in rows:
        actual = row["manual_score"] >= 55
        score = row.get(score_key)
        if score is None:
            abstain_positive += int(actual)
            abstain_negative += int(not actual)
        elif score >= threshold:
            tp += int(actual)
            fp += int(not actual)
        else:
            fn += int(actual)
            tn += int(not actual)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn + abstain_positive) if tp + fn + abstain_positive else 0.0
    specificity = tn / (tn + fp + abstain_negative) if tn + fp + abstain_negative else 0.0
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "abstain_positive": abstain_positive,
        "abstain_negative": abstain_negative,
        "coverage": round((tp + fp + tn + fn) / len(rows), 4),
        "precision": round(precision, 4),
        "recall_end_to_end": round(recall, 4),
        "specificity_end_to_end": round(specificity, 4),
        "f1_end_to_end": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "accuracy_end_to_end": round((tp + tn) / len(rows), 4),
        "balanced_accuracy_end_to_end": round((recall + specificity) / 2, 4),
    }


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2 + 1
        for position in order[start:end]:
            result[position] = rank
        start = end
    return result


def correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or statistics.pstdev(left) == 0 or statistics.pstdev(right) == 0:
        return None
    mean_left, mean_right = statistics.mean(left), statistics.mean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
    return round(numerator / denominator, 4)


def score_quality(rows: list[dict], score_key: str) -> dict:
    pairs = [(row["manual_score"], row[score_key]) for row in rows if row.get(score_key) is not None]
    manual = [pair[0] for pair in pairs]
    scores = [pair[1] for pair in pairs]
    return {
        "scored": len(pairs),
        "mae": round(statistics.mean(abs(a - b) for a, b in pairs), 2),
        "pearson": correlation(manual, scores),
        "spearman": correlation(ranks(manual), ranks(scores)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--run", type=Path, help="One run covering all 100 indices")
    parser.add_argument("--run20", type=Path)
    parser.add_argument("--run80", type=Path)
    parser.add_argument(
        "--overlay-run",
        type=Path,
        action="append",
        default=[],
        help="Optional partial run whose indexed results replace the base run",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manual = manual_rows(args.manual)
    if args.run:
        run_summaries = [read_json(args.run / "summary.json")]
        candidates = run_items(args.run)
    elif args.run20 and args.run80:
        run_summaries = [read_json(args.run20 / "summary.json"), read_json(args.run80 / "summary.json")]
        candidates = run_items(args.run20) | run_items(args.run80)
    else:
        parser.error("provide --run, or provide both --run20 and --run80")
    for overlay_run in args.overlay_run:
        run_summaries.append(read_json(overlay_run / "summary.json"))
        candidates.update(run_items(overlay_run))
    if set(candidates) != set(range(1, 101)):
        raise ValueError("candidate runs must cover exactly indices 1..100")

    rows = []
    selected_pages = official_pages = search_calls = extract_calls = 0
    failure_stages: dict[str, int] = {}
    for index in range(1, 101):
        candidate = candidates[index]
        source = source_result(args.source_run, index)
        meta = candidate.get("anysearch") or {}
        domain = str(meta.get("discovered_domain") or "").removeprefix("www.")
        urls = [str(url) for url in meta.get("selected_urls") or []]
        selected_pages += len(urls)
        official_pages += sum(
            bool(domain)
            and (urlparse(url).hostname or "").removeprefix("www.").lower() in {domain.lower(), f"www.{domain.lower()}"}
            for url in urls
        )
        search_calls += int(meta.get("search_calls") or 0)
        extract_calls += int(meta.get("extract_calls") or 0)
        stage = failure_stage(candidate)
        if stage:
            failure_stages[stage] = failure_stages.get(stage, 0) + 1
        baseline_score = source.get("validation", {}).get("score") if source.get("status") == "valid" else None
        rows.append(
            {
                **manual[index],
                "input_name": candidate.get("name"),
                "manual_label": "positive" if manual[index]["manual_score"] >= 55 else "negative",
                "baseline_score": baseline_score,
                "candidate_score": candidate.get("candidate_score"),
                "candidate_status": candidate.get("candidate_status"),
                "failure_stage": stage,
                "selected_urls": urls,
                **assessment_fields(candidate),
            }
        )

    scan = [confusion(rows, "candidate_score", threshold) for threshold in range(0, 101, 5)]
    best = max(scan, key=lambda item: (item["balanced_accuracy_end_to_end"], item["f1_end_to_end"], item["threshold"]))
    summary = {
        "companies": 100,
        "workers": max(int(summary["workers"]) for summary in run_summaries),
        "manual_positive": sum(row["manual_label"] == "positive" for row in rows),
        "manual_negative": sum(row["manual_label"] == "negative" for row in rows),
        "combined_seconds": round(sum(float(summary["seconds"]) for summary in run_summaries), 1),
        "baseline_at_55": confusion(rows, "baseline_score", 55),
        "candidate_at_55": confusion(rows, "candidate_score", 55),
        "baseline_score_quality": score_quality(rows, "baseline_score"),
        "candidate_score_quality": score_quality(rows, "candidate_score"),
        "best_threshold_by_balanced_accuracy": best,
        "threshold_scan": scan,
        "failure_stages": failure_stages,
        "retrieval": {
            "search_calls": search_calls,
            "extract_calls": extract_calls,
            "selected_pages": selected_pages,
            "official_domain_pages": official_pages,
            "official_domain_page_rate": round(official_pages / selected_pages, 4) if selected_pages else 0.0,
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in {"rows", "threshold_scan"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
