"""Reusable single-company adapter for the production research pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .company_research_trial import (
    DEFAULT_ENV_FILE,
    DEFAULT_HERMES,
    DEFAULT_OUTPUT_ROOT,
    load_env_file,
    localize_item,
    render_assessment,
    research_one,
    resolved_validator,
    validate_selected_records,
    write_reports,
)


REQUEST_FIELDS = frozenset({"name", "website", "linkedin_url"})
RESULT_FIELDS = (
    "trace_id",
    "status",
    "assessment",
    "validation",
    "report_markdown",
    "usage",
    "errors",
)


def _error_response(errors: list[str], trace_id: str = "") -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "status": "failed",
        "assessment": None,
        "validation": {"valid": False, "score": 0, "level": "低", "errors": errors, "warnings": []},
        "report_markdown": "",
        "usage": None,
        "errors": errors,
    }


def _url(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    value = value.strip()
    if not value:
        return ""
    if len(value) > 2048:
        raise ValueError(f"{field} must be at most 2048 characters")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field} must be an HTTP(S) URL")
    parsed = urlparse(value)
    try:
        host = parsed.hostname
    except ValueError:
        host = None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not host:
        raise ValueError(f"{field} must be an HTTP(S) URL")
    return value


def _request_record(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    extra = set(request) - REQUEST_FIELDS
    if extra:
        raise ValueError("request contains unsupported fields: " + ", ".join(sorted(map(str, extra))))
    name = request.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    name = name.strip()
    if len(name) > 300:
        raise ValueError("name must be at most 300 characters")
    record: dict[str, Any] = {"id": "input-001", "name": name}
    for field in ("website", "linkedin_url"):
        value = _url(request.get(field), field)
        if value:
            record[field] = value
    # Keep the production record contract and never mutate the caller's object.
    return validate_selected_records([record])[0]


def _path(value: str | Path, field: str) -> Path:
    try:
        return Path(value)
    except TypeError as exc:
        raise ValueError(f"{field} must be a path") from exc


def _check_options(timeout: int, reasoning: str, max_attempts: int, review_zero_score: bool) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 1800:
        raise ValueError("timeout must be between 1 and 1800")
    if reasoning not in {"low", "medium", "high"}:
        raise ValueError("reasoning must be low, medium, or high")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    if not isinstance(review_zero_score, bool):
        raise ValueError("review_zero_score must be a boolean")


def _check_runtime(env_file: Path, hermes: Path) -> None:
    load_env_file(env_file)
    for required in (resolved_validator(),):
        if not Path(required).is_file():
            raise RuntimeError(f"Project validator is unavailable: {required}")
    if not hermes.is_file() or not os.access(hermes, os.X_OK):
        raise RuntimeError(f"Hermes executable is unavailable: {hermes}")


def _new_run_dir(output_root: Path) -> tuple[str, Path]:
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ-api-n001")
    for suffix in ("", *[f"-{index}" for index in range(1, 100)]):
        trace_id = stamp + suffix
        run_dir = root / trace_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return trace_id, run_dir
    raise RuntimeError(f"Could not create a unique run directory under {root}")


def _write_summary(run_dir: Path, item: dict[str, Any]) -> None:
    duration = item.get("duration_seconds") or 0
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 0.0
    summary = {
        "selected": 1,
        "valid": int(item.get("status") == "valid"),
        "failed": int(item.get("status") != "valid"),
        "average_seconds": round(duration, 1),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def research_company(
    request: dict[str, Any],
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    env_file: str | Path = DEFAULT_ENV_FILE,
    hermes: str | Path = DEFAULT_HERMES,
    timeout: int = 300,
    reasoning: str = "medium",
    max_attempts: int = 3,
    review_zero_score: bool = True,
) -> dict[str, Any]:
    """Run one company through the unchanged production research chain."""
    record = _request_record(request)
    _check_options(timeout, reasoning, max_attempts, review_zero_score)
    output_root = _path(output_root, "output_root")
    env_file = _path(env_file, "env_file")
    hermes = _path(hermes, "hermes")
    _check_runtime(env_file, hermes)
    trace_id, run_dir = _new_run_dir(output_root)
    (run_dir / "selected-companies.json").write_text(
        json.dumps([record], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    item = research_one(
        record,
        index=1,
        run_dir=run_dir,
        hermes=hermes,
        timeout=timeout,
        reasoning=reasoning,
        max_attempts=max_attempts,
        review_zero_score=review_zero_score,
    )
    if not isinstance(item, dict):
        raise RuntimeError("research_one returned a non-object result")
    localize_item(item, hermes, timeout, reasoning)
    write_reports(run_dir, [item])
    _write_summary(run_dir, item)

    status = "valid" if item.get("status") == "valid" else "failed"
    validation = item.get("validation") if isinstance(item.get("validation"), dict) else _error_response([])["validation"]
    errors = list(dict.fromkeys(str(error) for error in item.get("errors") or []))
    if status == "failed":
        errors = list(dict.fromkeys(errors + [str(error) for error in validation.get("errors") or []]))
    assessment = item.get("assessment") if status == "valid" and isinstance(item.get("assessment"), dict) else None
    display_assessment = item.get("display_assessment") if isinstance(item.get("display_assessment"), dict) else assessment
    report_markdown = render_assessment(display_assessment, validation) if display_assessment is not None else ""
    return {
        "trace_id": trace_id,
        "status": status,
        "assessment": assessment,
        "validation": validation,
        "report_markdown": report_markdown,
        "usage": item.get("usage"),
        "errors": errors,
    }


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="Run one company through the production research pipeline")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--hermes", type=Path, default=DEFAULT_HERMES)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--reasoning", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--no-zero-review", action="store_true", help="Disable the one-time review of valid 0%% results")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        request = json.loads(sys.stdin.read())
        result = research_company(
            request,
            output_root=args.output_root,
            env_file=args.env_file,
            hermes=args.hermes,
            timeout=args.timeout,
            reasoning=args.reasoning,
            max_attempts=args.max_attempts,
            review_zero_score=not args.no_zero_review,
        )
    except (ValueError, RuntimeError, OSError, TypeError, json.JSONDecodeError) as exc:
        result = _error_response([str(exc)])
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
