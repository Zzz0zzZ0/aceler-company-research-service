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
  <meta name="theme-color" content="#fafafb">
  <title>Aceler 背调看板</title>
  <style>
    :root { color-scheme:light; --ground:#fafafb; --surface:#fff; --ink:#16161b; --muted:#626368; --quiet:#6f7178; --line:#e6e8ed; --line-strong:#cdd2dc; --blue:#104eec; --blue-soft:#eef3ff; --coral:#e36965; --coral-soft:#fff2f1; --success:#177245; --success-soft:#edf8f2; --amber:#a46100; --amber-soft:#fff7e7; --drawer:400px; }
    * { box-sizing:border-box; }
    html { background:var(--ground); }
    body { margin:0; min-width:320px; background:var(--ground); color:var(--ink); font:14px/1.55 "Avenir Next","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif; text-rendering:optimizeLegibility; }
    ::selection { background:#cbd8ff; color:#071d5e; }
    :focus-visible { outline:3px solid rgb(16 78 236 / 28%); outline-offset:2px; }
    button,input,select { font:inherit; }
    button,select { cursor:pointer; }
    button:disabled { cursor:wait; opacity:.58; }
    a { color:var(--blue); text-decoration-thickness:1px; text-underline-offset:3px; }
    h1,h2,h3,p { margin:0; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    .subtle { color:var(--muted); }
    .mono,.stat-value,.score-value,.row-score { font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace; font-variant-numeric:tabular-nums; }
    .app { height:100vh; min-height:620px; display:grid; grid-template-rows:64px minmax(0,1fr); overflow:hidden; }
    .app-header { display:grid; grid-template-columns:auto minmax(420px,1fr) auto; align-items:center; gap:28px; min-width:0; padding:0 24px; border-bottom:1px solid var(--line); background:rgb(250 250 251 / 94%); position:relative; z-index:20; }
    .brand { display:flex; align-items:baseline; gap:12px; white-space:nowrap; }
    .brand strong { font-size:24px; line-height:1; letter-spacing:-.04em; }
    .brand span { font-size:15px; font-weight:700; }
    .run-strip { display:flex; align-items:center; gap:18px; min-width:0; }
    .run-field { display:flex; align-items:center; gap:8px; min-width:0; }
    .run-field label,.stat-label { color:var(--muted); font-size:12px; font-weight:600; white-space:nowrap; }
    .run-field select { width:min(320px,27vw); min-height:36px; border:1px solid var(--line-strong); border-radius:5px; padding:6px 30px 6px 10px; color:var(--ink); background:var(--surface); }
    .header-stat { display:flex; align-items:baseline; gap:6px; white-space:nowrap; }
    .stat-value { font-size:17px; font-weight:750; }
    .header-stat.valid .stat-value { color:var(--success); }
    .header-stat.failed .stat-value { color:var(--coral); }
    #load-status { min-width:0; max-width:230px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--quiet); font-size:12px; }
    .primary-action { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:38px; padding:8px 15px; border:1px solid var(--blue); border-radius:5px; background:var(--blue); color:#fff; font-weight:750; box-shadow:0 4px 12px rgb(16 78 236 / 18%); }
    .primary-action:hover { background:#0c42cb; }
    .primary-action svg,.icon-button svg { width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
    .workspace { min-height:0; display:grid; grid-template-columns:minmax(330px,31%) minmax(0,1fr); }
    .queue { min-width:0; min-height:0; display:grid; grid-template-rows:auto auto minmax(0,1fr); border-right:1px solid var(--line); background:var(--surface); }
    .queue-header { display:flex; justify-content:space-between; align-items:baseline; gap:16px; padding:20px 22px 14px; }
    .queue-header h1 { font-size:19px; letter-spacing:-.02em; }
    #list-count { color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
    .queue-tools { display:grid; grid-template-columns:minmax(0,1fr) 112px; gap:8px; padding:0 22px 16px; border-bottom:1px solid var(--line); }
    .search-wrap { position:relative; }
    .search-wrap svg { position:absolute; left:11px; top:50%; width:16px; height:16px; transform:translateY(-50%); fill:none; stroke:var(--quiet); stroke-width:1.8; pointer-events:none; }
    input,select { width:100%; min-height:40px; border:1px solid var(--line-strong); border-radius:5px; padding:8px 10px; background:var(--surface); color:var(--ink); }
    .search-wrap input { padding-left:36px; }
    input::placeholder { color:#74767d; }
    .company-list { min-height:0; overflow:auto; scrollbar-color:#bcc2cc transparent; scrollbar-width:thin; }
    .company-row { appearance:none; width:100%; display:grid; gap:7px; border:0; border-bottom:1px solid var(--line); padding:13px 22px; background:var(--surface); color:inherit; text-align:left; position:relative; }
    .company-row:hover { background:#f7f9fd; }
    .company-row.selected { background:var(--blue-soft); }
    .company-row.selected::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--blue); }
    .row-top,.row-meta { display:flex; justify-content:space-between; align-items:center; gap:14px; min-width:0; }
    .row-name { min-width:0; overflow-wrap:anywhere; font-size:14px; font-weight:700; letter-spacing:-.01em; }
    .row-score { flex:0 0 auto; color:var(--blue); font-weight:750; }
    .row-meta { color:var(--muted); font-size:12px; }
    .row-context { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .status-text { display:inline-flex; align-items:center; gap:6px; flex:0 0 auto; font-weight:650; }
    .status-text::before { content:""; width:7px; height:7px; border:1px solid currentColor; border-radius:50%; background:currentColor; }
    .status-text.valid { color:var(--success); }
    .status-text.failed { color:var(--coral); }
    .detail { min-width:0; min-height:0; overflow:auto; padding:30px clamp(24px,3.4vw,54px) 48px; scrollbar-color:#bcc2cc transparent; scrollbar-width:thin; }
    .detail-empty { min-height:60vh; display:grid; place-items:center; text-align:center; color:var(--muted); }
    .detail-title { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:28px; align-items:end; padding-bottom:24px; border-bottom:1px solid var(--line-strong); }
    .detail-title h2 { max-width:24ch; overflow-wrap:anywhere; font-size:clamp(26px,3vw,38px); line-height:1.16; letter-spacing:-.038em; text-wrap:balance; }
    .detail-meta { margin-top:8px; color:var(--muted); }
    .summary-metrics { display:flex; gap:26px; align-items:stretch; }
    .summary-metric { min-width:104px; padding-left:18px; border-left:1px solid var(--line); }
    .summary-metric span { display:block; color:var(--muted); font-size:12px; font-weight:650; }
    .summary-metric strong { display:block; margin-top:4px; font-size:24px; line-height:1; }
    .score-value { color:var(--blue); }
    .detail-grid { display:grid; grid-template-columns:1fr 1fr; column-gap:clamp(26px,4vw,58px); }
    .module { min-width:0; padding:26px 0 28px; border-bottom:1px solid var(--line); }
    .module h3 { display:flex; align-items:center; gap:9px; margin-bottom:13px; font-size:17px; line-height:1.3; letter-spacing:-.015em; }
    .module h3::before { content:""; width:3px; height:18px; border-radius:2px; background:var(--blue); }
    .module p { max-width:74ch; white-space:pre-wrap; overflow-wrap:anywhere; }
    .module p + p,.module .kv + p { margin-top:12px; }
    .kv { display:grid; grid-template-columns:104px minmax(0,1fr); gap:7px 15px; margin:0; }
    .kv dt { color:var(--muted); }
    .kv dd { min-width:0; margin:0; overflow-wrap:anywhere; font-weight:550; }
    .match-line { display:flex; align-items:baseline; gap:9px; margin-bottom:15px; }
    .match-line strong { color:var(--blue); font-size:36px; line-height:1; letter-spacing:-.04em; }
    .match-line span { color:var(--muted); }
    .component-bars { display:grid; gap:8px; margin:16px 0; }
    .component-bar { display:grid; grid-template-columns:118px minmax(70px,1fr) 30px; gap:10px; align-items:center; color:var(--muted); font-size:12px; }
    .bar-track { height:3px; background:#e4e7ed; overflow:hidden; }
    .bar-fill { display:block; height:100%; background:var(--blue); }
    .direction { padding:12px 0; border-top:1px solid var(--line); }
    .direction:first-of-type { padding-top:0; border-top:0; }
    .direction-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:6px; }
    .direction-head strong { overflow-wrap:anywhere; }
    .tag { display:inline-flex; align-items:center; min-height:22px; padding:1px 7px; border-radius:999px; background:#eef0f4; color:#4f5158; font-size:11px; font-weight:750; white-space:nowrap; }
    .tag.high,.tag.valid { background:var(--success-soft); color:var(--success); }
    .tag.medium { background:var(--blue-soft); color:#244fa6; }
    .tag.low { background:var(--amber-soft); color:var(--amber); }
    .tag.failed { background:var(--coral-soft); color:#b33e3a; }
    .auxiliary { margin-top:0; padding:24px 0; border-bottom:1px solid var(--line); }
    .auxiliary summary { cursor:pointer; list-style:none; display:flex; justify-content:space-between; gap:20px; font-size:16px; font-weight:750; }
    .auxiliary summary::-webkit-details-marker { display:none; }
    .auxiliary summary::after { content:"＋"; color:var(--blue); font-size:18px; font-weight:500; }
    .auxiliary[open] summary::after { content:"−"; }
    .aux-grid { display:grid; grid-template-columns:1fr 1fr; gap:28px 48px; padding-top:22px; }
    .aux-block h3 { margin-bottom:9px; font-size:13px; }
    .source-list,.error-list { display:grid; gap:7px; margin:0; padding-left:18px; }
    .error { color:#b33e3a; }
    .empty { padding:44px 22px; color:var(--muted); text-align:center; }
    .drawer-backdrop { position:fixed; inset:64px 0 0; z-index:28; background:rgb(13 20 37 / 22%); opacity:0; transition:opacity 180ms cubic-bezier(.22,1,.36,1); pointer-events:none; }
    .drawer-backdrop.open { opacity:1; pointer-events:auto; }
    .research-drawer { position:fixed; z-index:30; inset:64px 0 0 auto; width:min(var(--drawer),100vw); display:grid; grid-template-rows:auto minmax(0,1fr); border-left:1px solid var(--line-strong); background:var(--surface); box-shadow:-18px 0 48px rgb(21 29 49 / 14%); transform:translateX(102%); visibility:hidden; transition:transform 180ms cubic-bezier(.22,1,.36,1),visibility 0s linear 180ms; }
    .research-drawer.open { transform:translateX(0); visibility:visible; transition-delay:0s; }
    .drawer-header { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; padding:24px 24px 18px; border-bottom:1px solid var(--line); }
    .drawer-header h2 { font-size:21px; letter-spacing:-.025em; }
    .drawer-header p { margin-top:4px; color:var(--muted); font-size:12px; }
    .icon-button { display:inline-grid; place-items:center; width:38px; height:38px; border:1px solid var(--line); border-radius:5px; background:var(--surface); color:var(--ink); }
    .drawer-body { overflow:auto; padding:24px; }
    .form-grid { display:grid; gap:18px; }
    .form-field { display:grid; gap:7px; font-weight:700; }
    .field-note { color:var(--quiet); font-size:11px; font-weight:500; }
    .form-actions { display:grid; gap:12px; margin-top:26px; }
    .form-actions .primary-action { width:100%; min-height:44px; }
    #research-status { min-height:44px; color:var(--muted); font-size:12px; }
    @media (max-width:1080px) {
      .app-header { grid-template-columns:auto 1fr auto; gap:16px; padding-inline:18px; }
      .run-strip { gap:12px; }
      .run-field select { width:220px; }
      #load-status { display:none; }
      .workspace { grid-template-columns:minmax(320px,38%) minmax(0,1fr); }
      .detail { padding-inline:28px; }
      .detail-grid { grid-template-columns:1fr; }
      .detail-title { grid-template-columns:1fr; align-items:start; }
      .summary-metrics { justify-content:flex-start; }
    }
    @media (max-width:760px) {
      .app { display:block; height:auto; min-height:100vh; overflow:visible; }
      .app-header { min-height:112px; grid-template-columns:1fr auto; align-content:center; gap:12px; padding:14px 16px; position:sticky; top:0; }
      .run-strip { grid-column:1/-1; display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:10px; }
      .run-field label { display:none; }
      .run-field select { width:100%; }
      .header-stat.selected { display:none; }
      .workspace { display:block; }
      .queue { min-height:0; max-height:56vh; border-right:0; border-bottom:1px solid var(--line-strong); }
      .company-list { max-height:38vh; }
      .detail { overflow:visible; padding:24px 18px 42px; }
      .detail-title h2 { font-size:28px; }
      .aux-grid { grid-template-columns:1fr; }
      .drawer-backdrop { inset:0; }
      .research-drawer { inset:0 0 0 auto; width:min(420px,100vw); }
    }
    @media (max-width:480px) {
      .brand strong { font-size:22px; }
      .brand span { display:none; }
      .primary-action { padding-inline:12px; }
      .queue-header,.queue-tools,.company-row { padding-left:16px; padding-right:16px; }
      .queue-tools { grid-template-columns:1fr 104px; }
      .summary-metrics { width:100%; gap:0; }
      .summary-metric { flex:1; min-width:0; }
      .component-bar { grid-template-columns:100px minmax(50px,1fr) 28px; }
    }
    @media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto!important; transition-duration:.01ms!important; } }
  </style>
</head>
<body>
  <!--
  THESIS: 结果审阅优先，拒绝统计卡堆叠；主张、证据和推断在同一视野对齐。
  OWN-WORLD: #FAFAFB 近白画布、#16161B 编辑墨色、钴蓝选区、珊瑚异常和发丝分隔线。
  STORY: 选择批次，扫描公司，核对四项判断与来源；需要时从顶栏打开单家公司背调。
  FIRST VIEWPORT: 64px 状态栏，左侧约 31% 公司队列，右侧研究正文，右侧抽屉按需覆盖。
  FORM: 事实核验编辑台，七项候选中的第六项；seed 20897b8c。
  FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
  -->
  <main id="app-shell" class="app">
    <header class="app-header">
      <div class="brand"><strong>Aceler</strong><span>背调看板</span></div>
      <div class="run-strip" aria-label="当前运行状态">
        <div class="run-field"><label for="run-select">运行批次</label><select id="run-select" aria-label="运行批次"></select></div>
        <div class="header-stat selected"><span class="stat-label">公司</span><strong id="stat-selected" class="stat-value">—</strong></div>
        <div class="header-stat valid"><span class="stat-label">有效</span><strong id="stat-valid" class="stat-value">—</strong></div>
        <div class="header-stat failed"><span class="stat-label">失败</span><strong id="stat-failed" class="stat-value">—</strong></div>
        <p id="load-status" role="status" aria-live="polite">正在加载…</p>
      </div>
      <button id="research-open" class="primary-action" type="button" aria-expanded="false" aria-controls="research-drawer"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>新建背调</button>
    </header>
    <section class="workspace" aria-label="背调结果工作区">
      <aside class="queue" aria-labelledby="queue-title">
        <div class="queue-header"><h1 id="queue-title">公司列表</h1><span id="list-count" aria-live="polite">—</span></div>
        <div class="queue-tools" aria-label="筛选条件">
          <label class="search-wrap" for="search"><span class="sr-only">搜索公司</span><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><input id="search" type="search" placeholder="搜索公司、行业或角色"></label>
          <label for="status-select"><span class="sr-only">状态筛选</span><select id="status-select"><option value="all">全部状态</option><option value="valid">有效</option><option value="failed">失败</option></select></label>
        </div>
        <div id="company-list" class="company-list"></div>
      </aside>
      <article id="detail" class="detail" aria-live="polite"><div class="detail-empty">选择左侧公司查看背调详情。</div></article>
    </section>
  </main>
  <div id="drawer-backdrop" class="drawer-backdrop" hidden></div>
  <aside id="research-drawer" class="research-drawer" role="dialog" aria-modal="true" aria-labelledby="research-title" aria-hidden="true">
    <div class="drawer-header"><div><h2 id="research-title">新建背调</h2><p>结果将保存为一个新的运行批次</p></div><button id="research-close" class="icon-button" type="button" aria-label="关闭新建背调"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>
    <div class="drawer-body">
      <form id="research-form">
        <div class="form-grid">
          <label class="form-field" for="research-name">公司名 <span class="field-note">必填</span><input id="research-name" name="name" type="text" maxlength="400" autocomplete="organization" required placeholder="输入公司全称"></label>
          <label class="form-field" for="research-website">官网 <span class="field-note">可选</span><input id="research-website" name="website" type="url" maxlength="2000" placeholder="https://example.com" autocomplete="url"></label>
          <label class="form-field" for="research-linkedin">LinkedIn <span class="field-note">可选</span><input id="research-linkedin" name="linkedin_url" type="url" maxlength="2000" placeholder="https://www.linkedin.com/company/..." autocomplete="url"></label>
        </div>
        <div class="form-actions"><button id="research-submit" class="primary-action" type="submit">开始背调</button><span id="research-status" role="status" aria-live="polite"></span></div>
      </form>
    </div>
  </aside>
  <script>
    const state = { runs: [], run: null, selected: null };
    const $ = id => document.getElementById(id);
    const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;', '"':'&quot;'}[c]));
    const scoreValue = item => item.score === null || item.score === undefined ? '—' : esc(item.score);
    const statusText = item => `<span class="status-text ${esc(item.status)}">${esc(item.status_label || item.status)}</span>`;
    const matchClass = value => /高/.test(value || '') ? 'high' : /中/.test(value || '') ? 'medium' : /低/.test(value || '') ? 'low' : '';
    const tag = (value, extra = '') => `<span class="tag ${extra || matchClass(value)}">${esc(value || '未确认')}</span>`;
    const link = item => item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.url)}</a>` : '';
    const componentLabels = { production_process_need:'生产工艺需求', catalog_fit:'产品目录匹配', consumption_intensity:'消耗强度', demand_recurrence:'需求复购', company_role_fit:'角色适配' };
    function setStats(stats) { ['selected','valid','failed'].forEach(key => $(`stat-${key}`).textContent = stats?.[key] ?? 0); }
    async function json(path) { const response = await fetch(path); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }
    function renderRunOptions() { $('run-select').innerHTML = state.runs.length ? state.runs.map(run => `<option value="${esc(run.run_id)}">${esc(run.label)} · ${run.stats.selected} 家</option>`).join('') : '<option>暂无运行结果</option>'; }
    function filtered() {
      const query = $('search').value.trim().toLowerCase(), status = $('status-select').value;
      return (state.run?.companies || []).filter(item => {
        const haystack = [item.name,item.industry,item.operational_role,item.commercial_relationship].join(' ').toLowerCase();
        return (!query || haystack.includes(query)) && (status === 'all' || item.status === status);
      });
    }
    function renderList() {
      const items = filtered(), total = state.run?.companies?.length || 0;
      $('list-count').textContent = `${items.length} / ${total}`;
      $('company-list').innerHTML = items.length ? items.map(item => `<button class="company-row ${state.selected?.record_id === item.record_id ? 'selected' : ''}" data-id="${esc(item.record_id)}" type="button" aria-pressed="${state.selected?.record_id === item.record_id}"><span class="row-top"><span class="row-name">${esc(item.name)}</span><span class="row-score">${scoreValue(item)}</span></span><span class="row-meta"><span class="row-context">${esc(item.industry)} · ${esc(item.operational_role)} · ${esc(item.commercial_relationship)}</span>${statusText(item)}</span></button>`).join('') : '<div class="empty">没有符合当前条件的公司。请调整搜索词或状态筛选。</div>';
      document.querySelectorAll('.company-row').forEach(button => button.addEventListener('click', () => { state.selected = (state.run.companies || []).find(item => item.record_id === button.dataset.id) || null; renderList(); renderDetail(); if (matchMedia('(max-width:760px)').matches) $('detail').scrollIntoView({behavior:'smooth',block:'start'}); }));
    }
    function renderDetail() {
      const item = state.selected, detail = $('detail');
      if (!item) { detail.innerHTML = '<div class="detail-empty">选择左侧公司查看背调详情。</div>'; return; }
      const assessment = item.assessment, crm = item.crm_record || {}, pos = assessment?.company_positioning, role = assessment?.role_judgment, match = assessment?.match;
      const components = Object.entries(match?.components || {});
      const componentHtml = components.length ? `<div class="component-bars">${components.map(([key,value]) => `<div class="component-bar"><span>${esc(componentLabels[key] || key)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.max(0,Math.min(100,Number(value) || 0))}%"></span></span><strong class="mono">${esc(value)}</strong></div>`).join('')}</div>` : '';
      const directionHtml = assessment?.procurement_directions?.length ? assessment.procurement_directions.map(direction => `<div class="direction"><div class="direction-head"><strong>${esc(direction.product || '未填写')}</strong>${tag(direction.priority || '未定')}</div><p>${esc(direction.application || '')}</p>${direction.basis ? `<p class="subtle">依据：${esc(direction.basis)}</p>` : ''}${direction.evidence_status ? `<p class="subtle">证据状态：${esc(direction.evidence_status)}</p>` : ''}${direction.next_question ? `<p class="subtle">下一步：${esc(direction.next_question)}</p>` : ''}</div>`).join('') : '<p class="subtle">未形成采购方向。</p>';
      const sources = assessment?.sources?.length ? `<ul class="source-list">${assessment.sources.map(link).map(value => `<li>${value}</li>`).join('')}</ul>` : '<p class="subtle">暂无来源链接。</p>';
      const errors = item.errors || [];
      detail.innerHTML = `<header class="detail-title"><div><h2>${esc(item.name)}</h2><p class="detail-meta">${esc(item.industry)} · ${esc(item.operational_role)} · ${esc(item.commercial_relationship)}</p></div><div class="summary-metrics"><div class="summary-metric"><span>匹配度</span><strong class="score-value mono">${scoreValue(item)}</strong></div><div class="summary-metric"><span>证据置信度</span><strong>${esc(match?.confidence || item.confidence)}</strong></div></div></header><div class="detail-grid"><section class="module"><h3>公司实质定位</h3><p>${esc(pos?.text || '暂无背调定位。')}</p></section><section class="module"><h3>角色判断</h3><dl class="kv"><dt>运营角色</dt><dd>${esc(role?.operational_role || item.operational_role)}</dd><dt>商业关系</dt><dd>${esc(role?.commercial_relationship || item.commercial_relationship)}</dd>${role?.secondary_relationship ? `<dt>次级关系</dt><dd>${esc(role.secondary_relationship)}</dd>` : ''}</dl><p>${esc(role?.reason || '暂无角色依据。')}</p></section><section class="module"><h3>匹配度</h3><div class="match-line"><strong class="mono">${scoreValue(item)}</strong><span>${esc(item.level || '未评分')}</span></div><dl class="kv"><dt>证据置信度</dt><dd>${tag(match?.confidence || item.confidence)}</dd><dt>准入门槛</dt><dd>${tag(match?.entry_barrier || item.entry_barrier)}</dd></dl>${componentHtml}<p>${esc(match?.rationale || '暂无匹配度说明。')}</p></section><section class="module"><h3>主要采购方向</h3>${directionHtml}</section></div><details class="auxiliary"><summary>来源与辅助信息</summary><div class="aux-grid"><section class="aux-block"><h3>来源链接</h3>${sources}</section><section class="aux-block"><h3>已确认信息</h3><dl class="kv"><dt>流程</dt><dd>${esc((assessment?.confirmed_processes || []).join('、') || '未确认')}</dd><dt>衬里系统</dt><dd>${esc((assessment?.confirmed_lining_systems || []).join('、') || '未确认')}</dd></dl></section>${errors.length ? `<section class="aux-block"><h3 class="error">错误 / 失败原因</h3><ul class="error-list">${errors.map(value => `<li>${esc(value)}</li>`).join('')}</ul></section>` : ''}<section class="aux-block"><h3>输入记录</h3><dl class="kv"><dt>公司名</dt><dd>${esc(crm.name || item.name)}</dd><dt>行业</dt><dd>${esc(crm.industry || item.industry)}</dd><dt>官网</dt><dd>${crm.website ? `<a href="${esc(crm.website)}" target="_blank" rel="noopener noreferrer">${esc(crm.website)}</a>` : '未填写'}</dd><dt>LinkedIn</dt><dd>${crm.linkedin_url ? `<a href="${esc(crm.linkedin_url)}" target="_blank" rel="noopener noreferrer">${esc(crm.linkedin_url)}</a>` : '未填写'}</dd><dt>背景</dt><dd>${esc(crm.background || '未填写')}</dd><dt>更新时间</dt><dd>${esc(crm.updated_at || '未填写')}</dd></dl></section></div></details>`;
    }
    function openResearch() { $('drawer-backdrop').hidden = false; $('app-shell').inert = true; requestAnimationFrame(() => { $('drawer-backdrop').classList.add('open'); $('research-drawer').classList.add('open'); }); $('research-drawer').setAttribute('aria-hidden','false'); $('research-open').setAttribute('aria-expanded','true'); setTimeout(() => $('research-name').focus(),180); }
    function closeResearch() { $('drawer-backdrop').classList.remove('open'); $('research-drawer').classList.remove('open'); $('research-drawer').setAttribute('aria-hidden','true'); $('research-open').setAttribute('aria-expanded','false'); $('app-shell').inert = false; setTimeout(() => { $('drawer-backdrop').hidden = true; $('research-open').focus(); },180); }
    function containDrawerFocus(event) { if (event.key !== 'Tab') return; const controls = [...$('research-drawer').querySelectorAll('button,input,select,a[href]')].filter(control => !control.disabled && control.offsetParent !== null); if (!controls.length) return; const first = controls[0], last = controls[controls.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
    async function loadRun(runId) { state.run = await json(`/api/runs/${encodeURIComponent(runId)}`); setStats(state.run.stats); state.selected = state.run.companies?.[0] || null; renderList(); renderDetail(); }
    async function refreshRuns() { state.runs = (await json('/api/runs')).runs || []; renderRunOptions(); }
    async function submitResearch(event) {
      event.preventDefault();
      const button = $('research-submit'), status = $('research-status');
      button.disabled = true; button.setAttribute('aria-busy','true'); status.textContent = '正在背调，请稍候。完成后将自动打开结果。';
      const payload = { name:$('research-name').value.trim(), website:$('research-website').value.trim(), linkedin_url:$('research-linkedin').value.trim() };
      try {
        const response = await fetch('/api/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.message || body.error || `HTTP ${response.status}`);
        await refreshRuns(); $('run-select').value = body.run_id; await loadRun(body.run_id);
        status.textContent = body.exit_code === 1 ? '背调完成，已打开结果；该公司结果为失败状态。' : '背调完成，已打开新结果。';
      } catch (error) { status.textContent = `提交失败：${error.message}。请检查输入后重试。`; }
      finally { button.disabled = false; button.removeAttribute('aria-busy'); }
    }
    async function start() { try { await refreshRuns(); if (state.runs.length) await loadRun(state.runs[0].run_id); else { setStats({}); renderList(); renderDetail(); } $('load-status').textContent = `已加载 ${state.runs.length} 个运行批次`; } catch (error) { $('load-status').textContent = `加载失败：${error.message}`; $('company-list').innerHTML = '<div class="empty error">无法读取本地运行结果。请检查服务日志后刷新页面。</div>'; } }
    $('research-open').addEventListener('click',openResearch); $('research-close').addEventListener('click',closeResearch); $('drawer-backdrop').addEventListener('click',closeResearch); $('research-drawer').addEventListener('keydown',containDrawerFocus); document.addEventListener('keydown',event => { if (event.key === 'Escape' && $('research-drawer').classList.contains('open')) closeResearch(); }); $('research-form').addEventListener('submit',submitResearch); $('run-select').addEventListener('change',event => loadRun(event.target.value).catch(error => $('load-status').textContent = `加载失败：${error.message}`)); $('search').addEventListener('input',renderList); $('status-select').addEventListener('change',renderList); start();
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
