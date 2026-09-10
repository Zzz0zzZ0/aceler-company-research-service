#!/usr/bin/env python3
"""Read-only paired retrieval evaluation against immutable human labels."""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from company_research_trial import company_research_trial as C
from company_research_trial.dashboard import _read_anysearch_key
from company_research_trial.retrieval_policy import research_with_policy, save

SOURCE = ROOT / "outputs/semantic-decision-validation/20260907T033244Z-testset100-3-m3"


def metrics(results, labels):
    counts = Counter()
    requests = 0
    for index, item in results.items():
        expected = labels[index]["follow_up"] == "跟进"
        valid = item.get("status") == "valid"
        predicted = ((item.get("assessment") or {}).get("match") or {}).get("follow_up") == "跟进"
        counts["valid"] += valid
        counts["positive"] += expected
        counts["tp" if expected and predicted else "fn" if expected else "fp" if predicted else "tn"] += valid
        meter = item.get("request_usage") or {}
        requests += meter.get("search_requests", 0) + meter.get("extract_requests", 0)
    return {**counts, "companies": len(results), "requests": requests,
            "recall": counts["tp"] / counts["positive"] if counts["positive"] else 0,
            "precision": counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0,
            "accuracy": (counts["tp"] + counts["tn"]) / len(results) if results else 0}


def run_arm(root, mode, indexes, records):
    run = root / mode
    C.ANYSEARCH_CACHE_DIR = run / "cold-cache"
    results = {}
    for i in indexes:
        path = C._record_dir(records[i], i, run) / "result.json"
        if path.exists():
            item = json.loads(path.read_text())
            policy = item.get("retrieval_policy") or {}
            needs_audit = mode == "website_first" and i % 10 == 0 and policy.get("used") == "website_first"
            if item.get("status") == "valid" and policy.get("requested") == mode and not needs_audit:
                results[i] = item
    pending = iter(i for i in indexes if i not in results)
    stopping = False
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {}
        def submit():
            if stopping:
                return
            i = next(pending, None)
            if i is not None:
                futures[pool.submit(research_with_policy, records[i], i, run, mode=mode, audit=i % 10 == 0)] = i
        for _ in range(5):
            submit()
        while futures:
            done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                i = futures.pop(future)
                try:
                    results[i] = future.result()
                except C.AnySearchQuotaExhausted:
                    stopping = True
                    results[i] = {"status": "quota_exhausted"}
                except Exception as exc:
                    results[i] = {"status": "failed", "errors": [C._redact_sensitive(str(exc))]}
                print(json.dumps({"mode": mode, "index": i, "status": results[i]["status"], "completed": len(results), "total": len(indexes)}), flush=True)
                save(root / "progress.json", {"state": "quota_paused" if stopping else "running", "mode": mode,
                    "completed": len(results), "total": len(indexes), "updated_at": time.time()})
                submit()
    if stopping:
        raise C.AnySearchQuotaExhausted("Evaluation paused for quota; valid checkpoints retained")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("paired", "full"))
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_dir.resolve(); root.mkdir(parents=True, exist_ok=True)
    C.load_env_file(C.DEFAULT_ENV_FILE)
    os.environ["ANYSEARCH_API_KEY"] = _read_anysearch_key(C.DEFAULT_ENV_FILE)
    os.environ["ANYSEARCH_STOP_ON_QUOTA"] = "1"
    source = json.loads((SOURCE / "summary.json").read_text())
    records = {i: row for i, row in enumerate(json.loads((SOURCE / "input-records.json").read_text()), 1)}
    labels = {row["index"]: row["manual"] for row in source["rows"]}
    rng = random.Random(20260910)
    paired = sorted(rng.sample([i for i in labels if labels[i]["follow_up"] == "跟进"], 10)
                    + rng.sample([i for i in labels if labels[i]["follow_up"] != "跟进"], 10))
    manifest = {"source": str(SOURCE), "labels_sha256": hashlib.sha256((SOURCE / "summary.json").read_bytes()).hexdigest(),
        "paired_indexes": paired, "seed": 20260910, "historical_full_metrics": source["metrics"],
        "gates": "paired: all quality metrics and valid count >= concurrent baseline; request reduction >=20%; full: all quality metrics >= historical 100-3, valid>=98"}
    if (root / "manifest.json").exists() and json.loads((root / "manifest.json").read_text()) != manifest:
        raise ValueError("Frozen validation manifest changed")
    save(root / "manifest.json", manifest)
    if args.phase == "paired":
        baseline = run_arm(root, "baseline", paired, records)
        candidate = run_arm(root, "website_first", paired, records)
        b, c = metrics(baseline, labels), metrics(candidate, labels)
        passed = all(c[k] >= b[k] for k in ("valid", "recall", "precision", "accuracy")) and c["requests"] <= b["requests"] * .8
        summary = {"phase": "paired", "baseline": b, "candidate": c, "passed": passed,
                   "request_reduction": 1-c["requests"]/b["requests"] if b["requests"] else 0,
                   "rows": [{"index": i, "label": labels[i], "baseline_score": (baseline[i].get("validation") or {}).get("score"),
                             "candidate_score": (candidate[i].get("validation") or {}).get("score")} for i in paired]}
    else:
        if not json.loads((root / "paired-summary.json").read_text())["passed"]:
            raise ValueError("Paired gate has not passed")
        candidate = run_arm(root, "website_first", sorted(records), records)
        c = metrics(candidate, labels)
        passed = c["valid"] >= 98 and all(round(c[k], 4) >= source["metrics"][k] for k in ("recall", "precision", "accuracy"))
        summary = {"phase": "full", "candidate": c, "historical_baseline": source["metrics"], "passed": passed}
    save(root / f"{args.phase}-summary.json", summary)
    save(root / "progress.json", {"state": "complete", "phase": args.phase, "passed": passed, "updated_at": time.time()})
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
