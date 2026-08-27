#!/usr/bin/env python3
"""Small local dashboard for company-research trial results.

Results remain read-only.  The only write-like action is a bounded, explicit
single-company research request which delegates to the existing CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "outputs" / "company-research-trial"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_INDUSTRIES = {
    "GANG_TIE_YE_JIN": "钢铁/冶金",
    "NAI_HUO_CAI_LIAO": "耐火材料",
    "ZHU_ZAO": "铸造",
    "TAO_CI": "陶瓷",
    "MO_LIAO": "磨料",
    "SHE_BEI_GONG_CHENG": "工业设备/工程",
    "MAO_YI_FEN_XIAO": "贸易/分销",
}
_STATUS_LABELS = {"valid": "有效", "failed": "失败"}
_MAX_TEXT = 6000
_MAX_RESEARCH_BODY = 16 * 1024
_MAX_RESEARCH_NAME = 400
_MAX_RESEARCH_URL = 2000
_RESEARCH_FIELDS = {"name", "website", "linkedin_url"}


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    """Coerce local JSON text to a bounded, display-safe string."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)[:limit]
    return ""


def _string_list(value: Any, limit: int = 20, item_limit: int = 600) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, item_limit) for item in value if _text(item, item_limit)][:limit]


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _score(validation: Any) -> int | float | None:
    """Read an existing validator score; never derive one in the dashboard."""
    if not isinstance(validation, dict):
        return None
    value = _number(validation.get("score"))
    if value is None or not 0 <= value <= 100:
        return None
    return value


def _http_url(value: Any) -> str:
    """Keep only external HTTP(S) links for safe clickable source fields."""
    value = _text(value, 2000).strip()
    if value.startswith(("https://", "http://")) and "\n" not in value and "\r" not in value:
        return value
    return ""


def _relative_to(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _safe_child(root: Path, name: str) -> Path | None:
    """Resolve a single local child while rejecting traversal and symlinks."""
    if not isinstance(name, str) or not _SAFE_ID.fullmatch(name) or name in {".", ".."}:
        return None
    path = root / name
    if path.is_symlink() or not path.is_dir() or not _relative_to(root, path):
        return None
    return path


def _read_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _record_sort_key(value: dict[str, Any]) -> tuple[int, str]:
    index = value.get("index")
    return (index if isinstance(index, int) else 10**9, _text(value.get("name")))


def _module_assessment(
    assessment: Any, validation: Any
) -> dict[str, Any] | None:
    """Project an assessment into the four report modules and support data."""
    if not isinstance(assessment, dict):
        return None

    positioning = assessment.get("company_positioning")
    role = assessment.get("role_judgment")
    match = assessment.get("match")
    positioning = positioning if isinstance(positioning, dict) else {}
    role = role if isinstance(role, dict) else {}
    match = match if isinstance(match, dict) else {}

    directions: list[dict[str, Any]] = []
    raw_directions = assessment.get("procurement_directions")
    if isinstance(raw_directions, list):
        for item in raw_directions[:30]:
            if not isinstance(item, dict):
                continue
            directions.append(
                {
                    "product": _text(item.get("product"), 240),
                    "priority": _text(item.get("priority"), 80),
                    "application": _text(item.get("application"), 800),
                    "basis": _text(item.get("basis"), 1800),
                    "evidence_status": _text(item.get("evidence_status"), 120),
                    "next_question": _text(item.get("next_question"), 800),
                }
            )

    sources: list[dict[str, str]] = []
    raw_sources = assessment.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources[:40]:
            if not isinstance(item, dict):
                continue
            url = _http_url(item.get("url"))
            if not url:
                continue
            sources.append(
                {
                    "id": _text(item.get("id"), 80),
                    "title": _text(item.get("title"), 500) or url,
                    "url": url,
                    "source_type": _text(item.get("source_type"), 120),
                }
            )

    components: dict[str, int | float] = {}
    raw_components = match.get("components")
    if isinstance(raw_components, dict):
        for key, value in raw_components.items():
            number = _number(value)
            if number is not None:
                components[_text(key, 100)] = number

    validation_score = _score(validation)
    validation_level = (
        _text(validation.get("level"), 80)
        if isinstance(validation, dict)
        else ""
    )
    return {
        "company_positioning": {
            "text": _text(positioning.get("text")),
            "evidence_ids": _string_list(positioning.get("evidence_ids"), 40, 80),
        },
        "role_judgment": {
            "operational_role": _text(role.get("operational_role"), 160),
            "commercial_relationship": _text(role.get("commercial_relationship"), 160),
            "secondary_relationship": _text(role.get("secondary_relationship"), 160),
            "reason": _text(role.get("reason")),
            "evidence_ids": _string_list(role.get("evidence_ids"), 40, 80),
        },
        "match": {
            "score": validation_score,
            "level": validation_level or "未评分",
            "confidence": _text(match.get("confidence"), 80) or "未确认",
            "entry_barrier": _text(match.get("entry_barrier"), 80) or "未确认",
            "rationale": _text(match.get("rationale")),
            "components": components,
        },
        "procurement_directions": directions,
        "confirmed_processes": _string_list(assessment.get("confirmed_processes"), 30, 200),
        "confirmed_lining_systems": _string_list(
            assessment.get("confirmed_lining_systems"), 30, 200
        ),
        "sources": sources,
    }


class DashboardData:
    """Read and curate result files below one configured output root."""

    def __init__(self, output_root: str | Path = DEFAULT_OUTPUT_ROOT):
        self.root = Path(output_root).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"output root is not a directory: {self.root}")

    def _run_dir(self, run_id: str) -> Path:
        run_dir = _safe_child(self.root, run_id)
        if run_dir is None:
            raise ValueError("invalid run id")
        if not ((run_dir / "summary.json").is_file() or (run_dir / "records").is_dir()):
            raise ValueError("run not found")
        return run_dir

    @staticmethod
    def _record_dirs(run_dir: Path) -> list[Path]:
        records_root = run_dir / "records"
        if records_root.is_symlink() or not records_root.is_dir():
            return []
        result: list[Path] = []
        for child in records_root.iterdir():
            if child.is_dir() and not child.is_symlink() and _SAFE_ID.fullmatch(child.name):
                result.append(child)
        return sorted(result, key=lambda item: item.name)

    def _record(self, record_dir: Path) -> dict[str, Any] | None:
        result = _read_json(record_dir / "result.json")
        if result is None:
            return None

        raw_record = result.get("record")
        raw_record = raw_record if isinstance(raw_record, dict) else {}
        assessment = result.get("display_assessment") or result.get("assessment")
        if assessment is None and _text(result.get("status"), 40).lower() == "valid":
            # Older complete records may keep the accepted assessment beside
            # result.json; it is still read through the same fixed filename.
            assessment = _read_json(record_dir / "accepted-assessment.json")
        validation = result.get("validation")
        validation = validation if isinstance(validation, dict) else {}
        module = _module_assessment(assessment, validation)
        status = _text(result.get("status"), 40).lower()
        legacy_failure = _text(result.get("defer_reason"), 300)
        if status == "deferred":
            status = "failed"
        if status not in _STATUS_LABELS:
            status = "failed"

        errors = _string_list(result.get("errors"), 10, 800)
        if legacy_failure and legacy_failure not in errors:
            errors.append(legacy_failure)

        name = _text(raw_record.get("name"), 400) or _text(
            assessment.get("company") if isinstance(assessment, dict) else "", 400
        ) or "未命名公司"
        industry_code = _text(raw_record.get("industry"), 100)
        role = module["role_judgment"] if module else {}
        match = module["match"] if module else {}
        score = _score(validation)
        level = _text(validation.get("level"), 80) or "未评分"
        return {
            "index": result.get("index") if isinstance(result.get("index"), int) else None,
            "record_id": _text(raw_record.get("id"), 200),
            "name": name,
            "industry": _INDUSTRIES.get(industry_code, industry_code or "未填写"),
            "industry_code": industry_code,
            "operational_role": _text(role.get("operational_role"), 160) or "未判断",
            "commercial_relationship": _text(role.get("commercial_relationship"), 160)
            or "未判断",
            "score": score,
            "level": level,
            "confidence": _text(match.get("confidence"), 80) or "未确认",
            "entry_barrier": _text(match.get("entry_barrier"), 80) or "未确认",
            "status": status,
            "status_label": _STATUS_LABELS[status],
            "duration_seconds": _number(result.get("duration_seconds")),
            "errors": errors,
            "assessment": module,
            "crm_record": {
                "id": _text(raw_record.get("id"), 200),
                "name": _text(raw_record.get("name"), 400),
                "website": _http_url(raw_record.get("website")),
                "linkedin_url": _http_url(raw_record.get("linkedin_url")),
                "country": _text(raw_record.get("country"), 160),
                "country_code": _text(raw_record.get("country_code"), 40),
                "industry": _INDUSTRIES.get(industry_code, industry_code),
                "industry_code": industry_code,
                "background": _text(raw_record.get("background")),
                "updated_at": _text(raw_record.get("updated_at"), 100),
                "contact_count": _number(raw_record.get("contact_count")),
                "weakness_reasons": _string_list(raw_record.get("weakness_reasons"), 20, 500),
            },
        }

    def _summary_stats(self, summary: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        counts = Counter(item["status"] for item in records)
        # If a run has no readable record files, retain its safe summary counts
        # so the overview still explains what the run selected.
        if records:
            selected = len(records)
            stats = {key: counts.get(key, 0) for key in _STATUS_LABELS}
        else:
            selected = summary.get("selected") if isinstance(summary.get("selected"), int) else 0
            stats = {
                key: summary.get(key) if isinstance(summary.get(key), int) else 0
                for key in _STATUS_LABELS
            }
            legacy_failed = summary.get("deferred")
            if isinstance(legacy_failed, int):
                stats["failed"] += legacy_failed
        return {
            "selected": selected,
            **stats,
            "average_seconds": _number(
                summary.get("average_seconds")
                if "average_seconds" in summary
                else summary.get("duration_seconds")
            ),
        }

    def _safe_run_overview(self, run_dir: Path) -> dict[str, Any]:
        summary = _read_json(run_dir / "summary.json") or {}
        records = [item for path in self._record_dirs(run_dir) if (item := self._record(path))]
        stats = self._summary_stats(summary, records)
        return {
            "run_id": run_dir.name,
            "label": run_dir.name,
            "stats": stats,
            "has_summary": bool(summary),
        }

    def runs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for child in self.root.iterdir():
            if not child.is_dir() or child.is_symlink() or not _SAFE_ID.fullmatch(child.name):
                continue
            if not ((child / "summary.json").is_file() or (child / "records").is_dir()):
                continue
            result.append(self._safe_run_overview(child))
        return sorted(result, key=lambda item: item["run_id"], reverse=True)

    def run(self, run_id: str) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        summary = _read_json(run_dir / "summary.json") or {}
        records = [item for path in self._record_dirs(run_dir) if (item := self._record(path))]
        records.sort(key=_record_sort_key)
        return {
            "run_id": run_dir.name,
            "label": run_dir.name,
            "stats": self._summary_stats(summary, records),
            "companies": records,
        }


class _ResearchInputError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _ResearchExecutionError(RuntimeError):
    pass


def _normalise_manual_url(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_field", f"{field} 必须是字符串"
        )
    value = value.strip()
    if not value:
        return ""
    if len(value) > _MAX_RESEARCH_URL:
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_field", f"{field} 长度不能超过 {_MAX_RESEARCH_URL} 个字符"
        )
    if any(char in value for char in "\r\n\t "):
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_field", f"{field} 不是有效网址"
        )
    candidate = value if "://" in value else f"https://{value}"
    parsed = None
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        hostname = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or "." not in hostname
        or parsed.username
        or parsed.password
    ):
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_field", f"{field} 不是有效网址"
        )
    return parsed._replace(fragment="").geturl().rstrip("/")


def _parse_research_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_json", "请求体必须是 JSON 对象"
        )
    unknown = sorted(set(payload) - _RESEARCH_FIELDS)
    if unknown:
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "unexpected_fields", "请求只接受 name、website、linkedin_url"
        )
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_name", "公司名不能为空"
        )
    name = name.strip()
    if len(name) > _MAX_RESEARCH_NAME:
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST,
            "invalid_name",
            f"公司名长度不能超过 {_MAX_RESEARCH_NAME} 个字符",
        )
    return {
        "name": name,
        "website": _normalise_manual_url(payload["website"], "website")
        if "website" in payload
        else "",
        "linkedin_url": _normalise_manual_url(payload["linkedin_url"], "linkedin_url")
        if "linkedin_url" in payload
        else "",
    }


def _read_research_payload(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    if handler.headers.get_content_type() != "application/json":
        raise _ResearchInputError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            "unsupported_media_type",
            "Content-Type 必须是 application/json",
        )
    raw_length = handler.headers.get("Content-Length")
    try:
        content_length = int(raw_length) if raw_length is not None else -1
    except ValueError:
        content_length = -1
    if content_length < 0:
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_content_length", "请求体长度无效"
        )
    if content_length > _MAX_RESEARCH_BODY:
        raise _ResearchInputError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "request_too_large",
            f"请求体不能超过 {_MAX_RESEARCH_BODY} 字节",
        )
    try:
        raw = handler.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise _ResearchInputError(
            HTTPStatus.BAD_REQUEST, "invalid_json", "请求体必须是有效 JSON"
        ) from None
    return _parse_research_payload(payload)


def _default_research_runner(command: list[str]) -> Any:
    """Run the existing CLI without a shell or any dashboard-side research logic."""
    return subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _existing_run_ids(root: Path) -> set[str]:
    try:
        children = root.iterdir()
    except OSError:
        return set()
    return {
        child.name
        for child in children
        if child.is_dir()
        and not child.is_symlink()
        and _SAFE_ID.fullmatch(child.name)
        and ((child / "summary.json").is_file() or (child / "records").is_dir())
    }


def _run_id_from_path(root: Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = Path(value.strip()).expanduser()
    candidates = [raw] if raw.is_absolute() else [PROJECT_DIR / raw, root / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.parent != root:
            continue
        safe = _safe_child(root, resolved.name)
        if safe is not None and (
            (safe / "summary.json").is_file() or (safe / "records").is_dir()
        ):
            return safe.name
    return None


def _research_result_run_id(result: Any, root: Path, before: set[str]) -> tuple[str, int]:
    if isinstance(result, dict):
        returncode = result.get("returncode")
        stdout = result.get("stdout") or ""
    elif isinstance(result, (str, Path)):
        returncode = 0
        stdout = json.dumps({"run_dir": str(result)}, ensure_ascii=False)
    else:
        returncode = getattr(result, "returncode", None)
        stdout = getattr(result, "stdout", "") or ""
    if returncode not in (0, 1):
        raise _ResearchExecutionError("research process failed")

    run_dir_values: list[Any] = []
    for line in reversed(str(stdout).splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "run_dir" in payload:
            run_dir_values.append(payload["run_dir"])
    for value in run_dir_values:
        run_id = _run_id_from_path(root, value)
        if run_id:
            return run_id, int(returncode)

    new_run_ids = sorted(_existing_run_ids(root) - before, reverse=True)
    if new_run_ids:
        return new_run_ids[0], int(returncode)
    raise _ResearchExecutionError("research result is unavailable")


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aceler 背调看板</title>
  <style>
    :root { color-scheme: light; --ink:#182332; --muted:#607083; --line:#dbe3eb; --panel:#fff; --wash:#f4f7fa; --blue:#1769aa; --bluewash:#e9f3fb; --green:#176b45; --greenwash:#e8f5ee; --amber:#8a5a00; --amberwash:#fff5da; --red:#9b2c2c; --redwash:#fff0f0; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--wash); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
    a { color:var(--blue); }
    .shell { max-width:1440px; margin:0 auto; padding:24px; }
    header { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:20px; }
    h1,h2,h3,p { margin:0; }
    h1 { font-size:clamp(24px,3vw,34px); letter-spacing:-.02em; }
    .subtle { color:var(--muted); }
    .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-bottom:16px; }
    .card,.panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; box-shadow:0 2px 12px rgb(30 55 80 / 4%); }
    .stat { padding:16px; }
    .stat strong { display:block; font-size:26px; line-height:1.2; margin-top:4px; }
    .stat.valid strong { color:var(--green); } .stat.failed strong { color:var(--red); }
    .research-form { padding:16px; margin-bottom:16px; }
    .research-form h2 { font-size:18px; margin-bottom:4px; }
    .research-form p { margin-bottom:12px; }
    .form-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .form-field { display:grid; gap:5px; }
    .form-field input { min-width:0; width:100%; }
    .form-actions { display:flex; align-items:center; gap:12px; margin-top:12px; }
    button[type="submit"] { min-height:40px; border:1px solid var(--blue); border-radius:8px; padding:8px 16px; color:#fff; background:var(--blue); font:inherit; font-weight:700; cursor:pointer; }
    button[type="submit"]:disabled { opacity:.6; cursor:wait; }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; padding:14px; align-items:center; }
    label { font-weight:600; }
    select,input { min-height:40px; border:1px solid #b9c5d2; border-radius:8px; padding:8px 10px; color:var(--ink); background:#fff; font:inherit; }
    input { min-width:220px; flex:1 1 250px; }
    .content { display:grid; grid-template-columns:minmax(390px,1fr) minmax(420px,1.25fr); gap:16px; align-items:start; }
    .list-panel { overflow:hidden; }
    .list-header { padding:14px 16px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:10px; }
    .company-list { display:grid; }
    .company-row { appearance:none; width:100%; border:0; border-bottom:1px solid var(--line); background:#fff; color:inherit; text-align:left; padding:14px 16px; cursor:pointer; }
    .company-row:hover,.company-row:focus-visible { background:#f0f6fb; outline:none; }
    .company-row.selected { box-shadow:inset 4px 0 var(--blue); background:var(--bluewash); }
    .row-top,.row-bottom { display:flex; justify-content:space-between; gap:12px; align-items:baseline; }
    .row-top strong { overflow-wrap:anywhere; }
    .row-bottom { color:var(--muted); font-size:13px; margin-top:6px; flex-wrap:wrap; }
    .badges { display:flex; gap:5px; flex-wrap:wrap; }
    .badge { display:inline-flex; align-items:center; min-height:24px; border:1px solid currentColor; border-radius:999px; padding:1px 8px; font-size:12px; font-weight:700; white-space:nowrap; }
    .badge.valid { color:var(--green); background:var(--greenwash); } .badge.failed { color:var(--red); background:var(--redwash); }
    .badge.match-high { color:var(--green); background:var(--greenwash); } .badge.match-medium { color:#1e5c91; background:var(--bluewash); } .badge.match-low { color:var(--amber); background:var(--amberwash); } .badge.match-none { color:var(--muted); background:#f3f5f7; }
    .detail { padding:20px; min-height:500px; }
    .detail-title { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:18px; }
    .detail-title h2 { overflow-wrap:anywhere; }
    .detail-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .module { border:1px solid var(--line); border-radius:10px; padding:14px; background:#fff; }
    .module.full { grid-column:1/-1; }
    .module h3 { font-size:16px; margin-bottom:8px; }
    .module p { white-space:pre-wrap; overflow-wrap:anywhere; }
    .kv { display:grid; grid-template-columns:110px 1fr; gap:5px 12px; margin:0; }
    .kv dt { color:var(--muted); } .kv dd { margin:0; overflow-wrap:anywhere; }
    .direction { padding:10px 0; border-top:1px solid var(--line); } .direction:first-child { border-top:0; padding-top:0; }
    .direction strong { display:inline-block; margin-right:8px; }
    details { margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }
    summary { cursor:pointer; font-weight:700; }
    .source-list,.error-list { display:grid; gap:6px; margin:8px 0 0; padding-left:20px; }
    .empty { padding:34px 16px; color:var(--muted); text-align:center; }
    .error { color:var(--red); }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    @media (max-width:900px) { .content { grid-template-columns:1fr; } .detail { min-height:0; } }
    @media (max-width:900px) { .form-grid { grid-template-columns:1fr 1fr; } .form-field:first-child { grid-column:1/-1; } }
    @media (max-width:560px) { .shell { padding:14px; } header { display:block; } .stats { grid-template-columns:repeat(2,1fr); } .detail-grid { grid-template-columns:1fr; } .module.full { grid-column:auto; } .kv { grid-template-columns:100px 1fr; } .form-grid { grid-template-columns:1fr; } .form-field:first-child { grid-column:auto; } .form-actions { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><h1>Aceler 背调看板</h1><p class="subtle">浏览本地背调运行结果 · 纯匹配度与证据置信度分开展示</p></div>
      <p id="load-status" class="subtle" role="status" aria-live="polite">正在加载…</p>
    </header>
    <section class="panel research-form" aria-labelledby="research-title">
      <h2 id="research-title">单家公司背调</h2>
      <p class="subtle">输入公司名，官网和 LinkedIn 可选；结果会生成新的运行批次。</p>
      <form id="research-form">
        <div class="form-grid">
          <label class="form-field" for="research-name">公司名（必填）<input id="research-name" name="name" type="text" maxlength="400" autocomplete="organization" required></label>
          <label class="form-field" for="research-website">官网（可选）<input id="research-website" name="website" type="url" maxlength="2000" placeholder="https://example.com" autocomplete="url"></label>
          <label class="form-field" for="research-linkedin">LinkedIn（可选）<input id="research-linkedin" name="linkedin_url" type="url" maxlength="2000" placeholder="https://www.linkedin.com/company/..." autocomplete="url"></label>
        </div>
        <div class="form-actions"><button id="research-submit" type="submit">开始背调</button><span id="research-status" class="subtle" role="status" aria-live="polite"></span></div>
      </form>
    </section>
    <section class="stats" aria-label="运行统计">
      <div class="card stat"><span class="subtle">当前运行公司</span><strong id="stat-selected">—</strong></div>
      <div class="card stat valid"><span>有效</span><strong id="stat-valid">—</strong></div>
      <div class="card stat failed"><span>失败</span><strong id="stat-failed">—</strong></div>
    </section>
    <section class="panel toolbar" aria-label="筛选条件">
      <label for="run-select">运行批次</label><select id="run-select"></select>
      <label for="search" class="sr-only">搜索公司</label><input id="search" type="search" placeholder="搜索公司名、行业或角色…">
      <label for="status-select" class="sr-only">状态筛选</label><select id="status-select"><option value="all">全部状态</option><option value="valid">有效</option><option value="failed">失败</option></select>
    </section>
    <section class="content">
      <div class="panel list-panel"><div class="list-header"><h2>公司列表</h2><span id="list-count" class="subtle" aria-live="polite">—</span></div><div id="company-list" class="company-list"></div></div>
      <article id="detail" class="panel detail" aria-live="polite"><div class="empty">选择左侧公司查看背调详情。</div></article>
    </section>
  </main>
  <script>
    const state = { runs: [], run: null, selected: null };
    const $ = id => document.getElementById(id);
    const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;', '"':'&quot;'}[c]));
    const display = value => value || '未填写';
    const scoreText = item => item.score === null || item.score === undefined ? '未评分' : `${esc(item.score)}% · ${esc(item.level || '未评分')}`;
    const matchClass = level => /高/.test(level || '') ? 'match-high' : /中/.test(level || '') ? 'match-medium' : /低/.test(level || '') ? 'match-low' : 'match-none';
    const statusBadge = item => `<span class="badge ${esc(item.status)}">${esc(item.status_label || item.status)}</span>`;
    const link = item => item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.url)}</a>` : '';
    function setStats(stats) { ['selected','valid','failed'].forEach(k => $(`stat-${k}`).textContent = stats?.[k] ?? 0); }
    async function json(path) { const response = await fetch(path); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }
    function renderRunOptions() {
      $('run-select').innerHTML = state.runs.length ? state.runs.map(run => `<option value="${esc(run.run_id)}">${esc(run.label)}（${run.stats.selected}家公司）</option>`).join('') : '<option>暂无运行结果</option>';
    }
    function filtered() {
      const query = $('search').value.trim().toLowerCase(), status = $('status-select').value;
      return (state.run?.companies || []).filter(item => {
        const hay = [item.name,item.industry,item.operational_role,item.commercial_relationship].join(' ').toLowerCase();
        return (!query || hay.includes(query)) && (status === 'all' || item.status === status);
      });
    }
    function renderList() {
      const items = filtered(); $('list-count').textContent = `${items.length} / ${state.run?.companies?.length || 0}`;
      $('company-list').innerHTML = items.length ? items.map(item => `<button class="company-row ${state.selected?.record_id === item.record_id ? 'selected' : ''}" data-id="${esc(item.record_id)}" type="button"><span class="row-top"><strong>${esc(item.name)}</strong><span class="badges">${statusBadge(item)}<span class="badge ${matchClass(item.level)}">${scoreText(item)}</span></span></span><span class="row-bottom"><span>${esc(item.industry)} · ${esc(item.operational_role)} · ${esc(item.commercial_relationship)}</span><span>置信度 ${esc(item.confidence)} · 准入 ${esc(item.entry_barrier)} · ${item.duration_seconds == null ? '耗时未知' : `${esc(item.duration_seconds)}s`}</span></span></button>`).join('') : '<div class="empty">没有符合条件的公司。</div>';
      document.querySelectorAll('.company-row').forEach(button => button.addEventListener('click', () => { state.selected = (state.run.companies || []).find(item => item.record_id === button.dataset.id) || null; renderList(); renderDetail(); }));
    }
    function renderDetail() {
      const item = state.selected, detail = $('detail');
      if (!item) { detail.innerHTML = '<div class="empty">选择左侧公司查看背调详情。</div>'; return; }
      const a = item.assessment, crm = item.crm_record || {}, pos = a?.company_positioning, role = a?.role_judgment, match = a?.match;
      const directionHtml = a?.procurement_directions?.length ? a.procurement_directions.map(d => `<div class="direction"><strong>${esc(d.product || '未填写')}</strong><span class="badge ${matchClass(d.priority)}">${esc(d.priority || '未定')}</span><p>${esc(d.application || '')}</p>${d.basis ? `<p class="subtle">依据：${esc(d.basis)}</p>` : ''}${d.evidence_status ? `<p class="subtle">证据状态：${esc(d.evidence_status)}</p>` : ''}${d.next_question ? `<p class="subtle">下一步：${esc(d.next_question)}</p>` : ''}</div>`).join('') : '<p class="subtle">未形成采购方向。</p>';
      const sources = a?.sources?.length ? `<ul class="source-list">${a.sources.map(link).map(x => `<li>${x}</li>`).join('')}</ul>` : '<p class="subtle">暂无来源链接。</p>';
      const errors = item.errors || [];
      detail.innerHTML = `<div class="detail-title"><div><h2>${esc(item.name)}</h2><p class="subtle">${esc(item.industry)} · ${esc(item.operational_role)} · ${esc(item.commercial_relationship)}</p></div><div class="badges">${statusBadge(item)}<span class="badge ${matchClass(item.level)}">${scoreText(item)}</span></div></div><div class="detail-grid"><section class="module"><h3>公司实质定位</h3><p>${esc(pos?.text || '暂无背调定位。')}</p></section><section class="module"><h3>角色判断</h3><dl class="kv"><dt>运营角色</dt><dd>${esc(role?.operational_role || item.operational_role)}</dd><dt>商业关系</dt><dd>${esc(role?.commercial_relationship || item.commercial_relationship)}</dd>${role?.secondary_relationship ? `<dt>次级关系</dt><dd>${esc(role.secondary_relationship)}</dd>` : ''}</dl><p>${esc(role?.reason || '暂无角色依据。')}</p></section><section class="module"><h3>匹配度</h3><dl class="kv"><dt>纯匹配度</dt><dd><span class="badge ${matchClass(match?.level || item.level)}">${scoreText(item)}</span></dd><dt>证据置信度</dt><dd>${esc(match?.confidence || item.confidence)}</dd><dt>准入门槛</dt><dd>${esc(match?.entry_barrier || item.entry_barrier)}</dd></dl><p>${esc(match?.rationale || '暂无匹配度说明。')}</p></section><section class="module"><h3>主要采购方向</h3>${directionHtml}</section></div><details><summary>来源与辅助信息</summary><h3>来源链接</h3>${sources}<h3>已确认流程</h3><p>${esc((a?.confirmed_processes || []).join('、') || '未确认')}</p><h3>已确认衬里系统</h3><p>${esc((a?.confirmed_lining_systems || []).join('、') || '未确认')}</p>${errors.length ? `<h3 class="error">错误 / 失败原因</h3><ul class="error-list">${errors.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}<h3>输入记录</h3><dl class="kv"><dt>公司名</dt><dd>${esc(crm.name || item.name)}</dd><dt>行业</dt><dd>${esc(crm.industry || item.industry)}</dd><dt>官网</dt><dd>${crm.website ? `<a href="${esc(crm.website)}" target="_blank" rel="noopener noreferrer">${esc(crm.website)}</a>` : '未填写'}</dd><dt>LinkedIn</dt><dd>${crm.linkedin_url ? `<a href="${esc(crm.linkedin_url)}" target="_blank" rel="noopener noreferrer">${esc(crm.linkedin_url)}</a>` : '未填写'}</dd><dt>提供的背景</dt><dd>${esc(crm.background || '未填写')}</dd><dt>更新时间</dt><dd>${esc(crm.updated_at || '未填写')}</dd></dl></details>`;
    }
    async function loadRun(runId) { state.run = await json(`/api/runs/${encodeURIComponent(runId)}`); setStats(state.run.stats); state.selected = state.run.companies?.[0] || null; renderList(); renderDetail(); }
    async function refreshRuns() { state.runs = (await json('/api/runs')).runs || []; renderRunOptions(); }
    async function submitResearch(event) {
      event.preventDefault();
      const button = $('research-submit'), status = $('research-status');
      button.disabled = true; status.textContent = '正在背调，请稍候…';
      const payload = { name: $('research-name').value.trim(), website: $('research-website').value.trim(), linkedin_url: $('research-linkedin').value.trim() };
      try {
        const response = await fetch('/api/research', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.message || body.error || `HTTP ${response.status}`);
        await refreshRuns(); $('run-select').value = body.run_id; await loadRun(body.run_id);
        status.textContent = body.exit_code === 1 ? '背调完成，已打开结果（其中可能有失败公司）。' : '背调完成，已打开结果。';
      } catch (error) { status.textContent = `提交失败：${error.message}`; }
      finally { button.disabled = false; }
    }
    async function start() { try { await refreshRuns(); if (state.runs.length) await loadRun(state.runs[0].run_id); else { setStats({}); renderList(); renderDetail(); } $('load-status').textContent = `已加载 ${state.runs.length} 个运行批次`; } catch (error) { $('load-status').textContent = `加载失败：${error.message}`; $('company-list').innerHTML = '<div class="empty error">无法读取本地运行结果。</div>'; } }
    $('research-form').addEventListener('submit', submitResearch); $('run-select').addEventListener('change', event => loadRun(event.target.value).catch(error => $('load-status').textContent = `加载失败：${error.message}`)); $('search').addEventListener('input', renderList); $('status-select').addEventListener('change', renderList); start();
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP adapter exposing the dashboard, read APIs, and one manual task."""

    server_version = "AcelerDashboard/1"
    sys_version = ""

    @property
    def data(self) -> DashboardData:
        return self.server.dashboard_data  # type: ignore[attr-defined]

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _research(self) -> None:
        try:
            payload = _read_research_payload(self)
        except _ResearchInputError as exc:
            self._json(exc.status, {"error": exc.code, "message": exc.message})
            return

        research_lock = self.server.research_lock  # type: ignore[attr-defined]
        if not research_lock.acquire(blocking=False):
            self._json(
                HTTPStatus.CONFLICT,
                {"error": "research_in_progress", "message": "已有一家公司正在背调，请稍候"},
            )
            return
        try:
            before = _existing_run_ids(self.data.root)
            record = {"id": "manual", "name": payload["name"]}
            for field in ("website", "linkedin_url"):
                if payload[field]:
                    record[field] = payload[field]
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", prefix="aceler-research-", delete=True
            ) as selected_file:
                json.dump([record], selected_file, ensure_ascii=False)
                selected_file.flush()
                command = [
                    sys.executable,
                    "-m",
                    "company_research_trial.company_research_trial",
                    "--selected-file",
                    selected_file.name,
                    "--output-root",
                    str(self.data.root),
                    "--workers",
                    "1",
                ]
                try:
                    result = self.server.research_runner(command)  # type: ignore[attr-defined]
                    run_id, returncode = _research_result_run_id(result, self.data.root, before)
                except (OSError, _ResearchExecutionError):
                    self._json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "research_failed", "message": "背调执行失败，请检查服务日志"},
                    )
                    return
            self._json(
                HTTPStatus.OK,
                {"run_id": run_id, "status": "completed", "exit_code": returncode},
            )
        finally:
            research_lock.release()

    def do_HEAD(self) -> None:  # noqa: N802
        if urlsplit(self.path).path in {"/", "/index.html"}:
            self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/runs":
            self._json(HTTPStatus.OK, {"runs": self.data.runs()})
            return
        prefix = "/api/runs/"
        if path.startswith(prefix):
            run_id = unquote(path[len(prefix) :])
            try:
                payload = self.data.run(run_id)
            except (ValueError, OSError):
                self._json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                return
            self._json(HTTPStatus.OK, payload)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/api/research":
            self._research()
            return
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = _method_not_allowed  # noqa: N815
    do_PATCH = _method_not_allowed  # noqa: N815
    do_DELETE = _method_not_allowed  # noqa: N815
    do_OPTIONS = _method_not_allowed  # noqa: N815
    do_TRACE = _method_not_allowed  # noqa: N815
    do_CONNECT = _method_not_allowed  # noqa: N815


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    research_runner: Callable[[list[str]], Any] | None = None,
) -> ThreadingHTTPServer:
    data = DashboardData(output_root)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.dashboard_data = data  # type: ignore[attr-defined]
    # ponytail: one global manual-task lock; per-user queues are unnecessary for this local dashboard.
    server.research_lock = threading.Lock()  # type: ignore[attr-defined]
    server.research_runner = research_runner or _default_research_runner  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local Aceler research dashboard")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port, args.output_root)
    print(f"Aceler 背调看板: http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
