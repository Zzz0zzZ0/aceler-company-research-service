"""Opt-in website-first retrieval; negative decisions retain the full baseline check."""
from pathlib import Path
import json
import os
import time

from . import company_research_trial as C


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def website_pack(record):
    name = record["name"]
    seed = C._normalise_url(str(record.get("website") or ""))
    domain = C.hostname(seed)
    if not seed or not domain:
        raise C.AnySearchPackError("No website seed; use baseline identity discovery")
    pages = []
    seen = set()
    local_calls = 0

    def fetch(url):
        nonlocal local_calls
        key = C._provenance_url_key(url)
        if not key or key in seen or not C._trusted_url(url, domain):
            return
        seen.add(key)
        local_calls += 1
        try:
            text = C._fallback_extract_output(url, 15)
        except Exception:
            return
        if C._substantive_extract(text):
            pages.append((url, text))

    fetch(seed)
    if not pages:
        raise C.AnySearchPackError("Website seed unreadable; use baseline retrieval")
    linked = [url for _, text in pages for url in C._search_result_urls(text)
              if C._trusted_url(url, domain) and C._page_path_intent(url)]
    linked = C._rank_urls(linked, "", name, domain)
    linked.sort(key=C._page_path_intent, reverse=True)
    for url in linked[:3]:
        fetch(url)
    queries = []
    if len(pages) < 3:
        queries = [f'"{C._business_search_name(name)}" site:{domain} products services',
                   f'"{C._business_search_name(name)}" site:{domain} manufacturing applications']
        output = C.run_anysearch_cli(["batch_search", "--query", queries[0], "--query", queries[1], "--max_results", "5"], timeout=20)
        for url in C._rank_urls(C._search_result_urls(output), output, name, domain)[:4]:
            fetch(url)
    pages, scores = C._select_relevant_pages(pages, name, domain, 3)
    if not pages:
        raise C.AnySearchPackError("No substantive website pages")
    sections = ["# Website-first identity-seeded sources"]
    for index, (url, text) in enumerate(pages, 1):
        sections.extend(["", f"## S{index}", f"URL: {url}", f"Title: {C._extract_title(text, url)}", "", text])
    return "\n".join(sections) + "\n", {"mode": "website_first", "selected_urls": [url for url, _ in pages],
        "selected_page_scores": scores, "queries": queries, "local_extract_calls": local_calls,
        "search_calls": int(bool(queries)), "extract_calls": 0, "cache_hit": False}


def positive(item):
    assessment = item.get("assessment") or {}
    validation = item.get("validation") or {}
    score = validation.get("score")
    return (item.get("status") == "valid" and validation.get("valid") is True
            and assessment.get("identity_status") == "confirmed"
            and isinstance(score, (int, float)) and not isinstance(score, bool) and score >= 55
            and (assessment.get("match") or {}).get("follow_up") == "跟进")


def research_with_policy(record, index, run_dir, *, mode="baseline", audit=False, researcher=None, refresh=False):
    if mode not in {"baseline", "website_first"}:
        raise ValueError("Unknown retrieval mode")
    researcher = researcher or C.research_one
    directory = C._record_dir(record, index, Path(run_dir))
    directory.mkdir(parents=True, exist_ok=True)
    meter_path = directory / "request-usage.json"
    meter = json.loads(meter_path.read_text()) if meter_path.exists() else {
        "search_requests": 0, "extract_requests": 0, "cli_attempts": 0, "billing_units": "unknown"}
    token = C.ANYSEARCH_REQUEST_METER.set(meter)
    started = time.monotonic()
    policy = {"requested": mode, "used": "baseline", "audited": False}
    try:
        if mode == "baseline":
            item = researcher(record, index, run_dir, **({"refresh_evidence_cache": True} if refresh else {}))
        else:
            candidate = None
            try:
                candidate_path = directory / "website-first-candidate.json"
                if candidate_path.exists():
                    candidate = json.loads(candidate_path.read_text())
                if not candidate or candidate.get("status") != "valid":
                    pack, metadata = website_pack(record)
                    candidate = researcher(record, index, Path(run_dir) / "website-first-trial", evidence_pack=pack, use_anysearch=False)
                    candidate["anysearch"] = metadata
                    save(directory / "anysearch-meta.json", metadata)
                    save(candidate_path, candidate)
            except C.AnySearchQuotaExhausted:
                raise
            except Exception as exc:
                policy["website_error"] = C._redact_sensitive(str(exc))[:600]
            if candidate and positive(candidate) and not audit:
                item = candidate
                policy["used"] = "website_first"
            else:
                baseline_run = Path(run_dir) / "baseline-confirmation"
                baseline_path = C._record_dir(record, index, baseline_run) / "result.json"
                item = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
                if not item or item.get("status") != "valid":
                    item = researcher(record, index, baseline_run, **({"refresh_evidence_cache": True} if refresh else {}))
                policy.update({"used": "baseline_confirmation", "audited": bool(candidate and audit),
                    "candidate_positive": bool(candidate and positive(candidate)), "baseline_positive": positive(item),
                    "baseline_record_dir": str(C._record_dir(record, index, baseline_run))})
                if candidate and positive(candidate) and not positive(item):
                    policy["quality_alert"] = "Website positive was not confirmed by the full baseline"
        item["record_dir"] = str(directory)
        item["retrieval_policy"] = policy
        item["request_usage"] = meter
        item["duration_seconds"] = round(time.monotonic() - started, 1)
        save(directory / "result.json", item)
        return item
    finally:
        save(directory / "request-usage.json", meter)
        C.ANYSEARCH_REQUEST_METER.reset(token)
