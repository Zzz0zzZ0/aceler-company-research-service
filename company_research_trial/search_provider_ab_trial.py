#!/usr/bin/env python3
"""Live retrieval A/B: Hermes built-in web search vs AnySearch."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from company_research_trial.company_research_trial import (
    DEFAULT_HERMES,
    DEFAULT_OUTPUT_ROOT,
    _redact_sensitive,
    anysearch_pack,
    child_environment,
    extract_json_object,
    load_env_file,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_RUN = DEFAULT_OUTPUT_ROOT / "20260824T015217Z"
SAMPLE_INDICES = (12, 13, 28, 34, 49)


def prompt_for(record: dict[str, Any]) -> str:
    return f"""You are running a search-engine evidence retrieval test. Research only this exact company; do not search for people and do not score it.
Company: {record['name']}
Specified website: {record.get('website') or 'none'}

Use only web_search and web_extract. Run at most two searches and extract at most two page bodies. Prefer company, product, and process pages on the specified official website; use a reliable registry or industry source only when the official site is insufficient. Search-result snippets are not evidence. Guard against same-name entities.

Find: (1) whether the exact entity matches the specified site; (2) its main revenue activity: manufacturing, extracting, reselling, designing, installing, or operating production; (3) explicit products and processes relevant to refractory, steel, foundry, ceramic, abrasive, or industrial-furnace work; and (4) material gaps.

Return exactly one JSON object, without Markdown:
{{
  "company": "...",
  "identity_status": "confirmed|ambiguous|wrong_entity",
  "main_business": "...",
  "operational_actions": ["..."],
  "relevant_processes": ["..."],
  "sources": [{{
    "title": "...",
    "url": "https://...",
    "source_type": "official|registry|industry|media|other",
    "official": true,
    "claims": ["facts directly supported by the extracted page body"]
  }}],
  "gaps": ["..."]
}}
If extraction fails or exact-entity evidence is unavailable, use ambiguous; never fill gaps with a same-name company."""


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:50] or "company"


def run_hermes(index: int, record: dict[str, Any], record_dir: Path) -> dict[str, Any]:
    usage_path = record_dir / "hermes-web-usage.json"
    env = child_environment()
    for key in list(env):
        if key.startswith("ANYSEARCH_"):
            env.pop(key, None)
    command = [
        str(DEFAULT_HERMES),
        "--reasoning",
        "medium",
        "--ignore-rules",
        "--toolsets",
        "web",
        "--usage-file",
        str(usage_path),
        "--oneshot",
        prompt_for(record),
    ]
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=record_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=360,
        )
        raw = _redact_sensitive(result.stdout or "")
        (record_dir / "hermes-web-raw.txt").write_text(raw, encoding="utf-8")
        (record_dir / "hermes-web-stderr.txt").write_text(
            _redact_sensitive(result.stderr or ""), encoding="utf-8"
        )
        evidence = extract_json_object(raw)
        (record_dir / "hermes-web-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "arm": "hermes_web",
            "index": index,
            "company": record["name"],
            "ok": result.returncode == 0,
            "seconds": round(time.monotonic() - started, 1),
            "returncode": result.returncode,
        }
    except Exception as exc:
        (record_dir / "hermes-web-error.txt").write_text(
            _redact_sensitive(f"{type(exc).__name__}: {exc}"), encoding="utf-8"
        )
        return {
            "arm": "hermes_web",
            "index": index,
            "company": record["name"],
            "ok": False,
            "seconds": round(time.monotonic() - started, 1),
            "error": type(exc).__name__,
        }


def main() -> int:
    load_env_file(PROJECT_DIR / "config" / "local.env")
    records = json.loads((SOURCE_RUN / "selected-companies.json").read_text(encoding="utf-8"))
    selected = {index: records[index - 1] for index in SAMPLE_INDICES}
    run_dir = DEFAULT_OUTPUT_ROOT / "search-provider-ab" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-hermes-exa-v-anysearch"
    )
    records_dir = run_dir / "records"
    records_dir.mkdir(parents=True)
    (run_dir / "selection.json").write_text(
        json.dumps(
            [{"index": index, **selected[index]} for index in SAMPLE_INDICES],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_dir": str(run_dir), "indices": SAMPLE_INDICES}), flush=True)

    company_dirs: dict[int, Path] = {}
    for index, record in selected.items():
        record_dir = records_dir / f"{index:03d}-{slug(record['name'])}"
        record_dir.mkdir()
        company_dirs[index] = record_dir
        started = time.monotonic()
        try:
            pack, meta = anysearch_pack(record, max_sources=2)
            (record_dir / "anysearch-evidence.md").write_text(pack, encoding="utf-8")
            (record_dir / "anysearch-meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            outcome = {
                "arm": "anysearch",
                "index": index,
                "company": record["name"],
                "ok": True,
                "seconds": round(time.monotonic() - started, 1),
                "sources": len(meta.get("selected_urls") or []),
            }
        except Exception as exc:
            (record_dir / "anysearch-error.txt").write_text(
                _redact_sensitive(f"{type(exc).__name__}: {exc}"), encoding="utf-8"
            )
            outcome = {
                "arm": "anysearch",
                "index": index,
                "company": record["name"],
                "ok": False,
                "seconds": round(time.monotonic() - started, 1),
                "error": type(exc).__name__,
            }
        print(json.dumps(outcome, ensure_ascii=False), flush=True)

    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(run_hermes, index, selected[index], company_dirs[index]): index
            for index in SAMPLE_INDICES
        }
        for future in concurrent.futures.as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            print(json.dumps(outcome, ensure_ascii=False), flush=True)
    (run_dir / "run-complete.json").write_text(
        json.dumps({"completed": True, "hermes": outcomes}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if all(outcome["ok"] for outcome in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
