#!/usr/bin/env python3
"""Validate and score a structured Aceler company assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROLES = {"终端用户", "耐材生产商", "贸易商", "分销商", "工程公司", "同行", "其他/公开资料不足"}
RELATIONSHIPS = {"潜在客户", "渠道合作伙伴", "同行", "低匹配客户"}
LEVELS = {"高", "中", "低"}
EVIDENCE_STATES = {"已确认", "推测", "公开资料未确认"}
SOURCE_TYPES = {"官网", "官方领英", "政府/注册", "公司文件", "项目业主/政府", "行业组织", "可靠媒体", "其他"}
CATALOG_PRODUCTS = {
    "Dead Burned Magnesite",
    "Caustic Calcined Magnesite",
    "Fused Magnesite",
    "Silicon Carbide",
    "Fused Silica",
    "Calcium Aluminate",
    "Tabular Alumina",
    "White Fused Alumina",
    "Brown Fused Alumina",
    "Steel Fiber",
    "Steel Rod",
    "Spinel / Alumina-Magnesia",
    "High Alumina Cement",
    "Magnesia Bricks",
    "Magnesia Carbon Bricks",
    "Sprue Cup / Sprue Bowl",
    "Aluminum Silicon Ceramic Crucible",
    "Ceramic Core",
    "Graphite Electrode",
    "Wax for Precision Casting",
    "Bauxite",
    "Chamotte",
    "Mullite",
    "Fumed Silica",
    "Calcined Alpha Alumina",
    "Calcium Aluminate Cement & PAC",
}
COMPONENT_LIMITS = {
    "production_process_need": 30,
    "catalog_fit": 30,
    "consumption_intensity": 20,
    "demand_recurrence": 10,
    "company_role_fit": 10,
}
def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def score_level(score: int) -> str:
    if score >= 80:
        return "高"
    if score >= 55:
        return "中"
    return "低"


def validate(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data.get("company"), str) or not data["company"].strip():
        errors.append("company must be a non-empty string")

    identity = data.get("identity_status")
    if identity not in {"confirmed", "ambiguous"}:
        errors.append("identity_status must be confirmed or ambiguous")
    if data.get("research_status") not in {"complete", "partial"}:
        errors.append("research_status must be complete or partial")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must contain at least one source")
        sources = []
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"sources[{index}].id must be non-empty")
        elif source_id in source_ids:
            errors.append(f"duplicate source id: {source_id}")
        else:
            source_ids.add(source_id)
        if not isinstance(source.get("title"), str) or not source["title"].strip():
            errors.append(f"sources[{index}].title must be non-empty")
        if not is_http_url(source.get("url")):
            errors.append(f"sources[{index}].url must be an http(s) URL")
        if source.get("source_type") not in SOURCE_TYPES:
            errors.append(f"sources[{index}].source_type is invalid")

    positioning = data.get("company_positioning")
    if not isinstance(positioning, dict) or not str(positioning.get("text", "")).strip():
        errors.append("company_positioning.text must be non-empty")
    else:
        check_evidence_ids(positioning.get("evidence_ids"), source_ids, "company_positioning", errors)

    role = data.get("role_judgment")
    relationship = None
    if not isinstance(role, dict):
        errors.append("role_judgment must be an object")
    else:
        if role.get("operational_role") not in ROLES:
            errors.append("role_judgment.operational_role is invalid")
        relationship = role.get("commercial_relationship")
        if relationship not in RELATIONSHIPS:
            errors.append("role_judgment.commercial_relationship is invalid")
        secondary = role.get("secondary_relationship", "")
        if secondary and secondary not in RELATIONSHIPS:
            errors.append("role_judgment.secondary_relationship is invalid")
        if not str(role.get("reason", "")).strip():
            errors.append("role_judgment.reason must be non-empty")
        check_evidence_ids(role.get("evidence_ids"), source_ids, "role_judgment", errors)

    match = data.get("match")
    total = 0
    if not isinstance(match, dict):
        errors.append("match must be an object")
        match = {}
    components = match.get("components")
    if not isinstance(components, dict):
        errors.append("match.components must be an object")
        components = {}
    for name, maximum in COMPONENT_LIMITS.items():
        value = components.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            errors.append(f"match.components.{name} must be an integer from 0 to {maximum}")
        else:
            total += value

    for flag in (
        "only_industry_label",
        "relevant_process_or_business_confirmed",
        "official_core_evidence",
        "sourcing_or_channel_signal_confirmed",
    ):
        if not isinstance(match.get(flag), bool):
            errors.append(f"match.{flag} must be true or false")

    if match.get("confidence") not in LEVELS:
        errors.append("match.confidence must be 高, 中, or 低")
    if match.get("entry_barrier") not in LEVELS:
        errors.append("match.entry_barrier must be 高, 中, or 低")
    if not str(match.get("rationale", "")).strip():
        errors.append("match.rationale must be non-empty")

    score = total - total % 5
    level = score_level(score)

    processes = data.get("confirmed_processes")
    if not isinstance(processes, list) or not all(isinstance(item, str) for item in processes):
        errors.append("confirmed_processes must be a list of strings")
        processes = []
    lining_systems = data.get("confirmed_lining_systems", [])
    if not isinstance(lining_systems, list) or not all(isinstance(item, str) for item in lining_systems):
        errors.append("confirmed_lining_systems must be a list of strings")
        lining_systems = []

    directions = data.get("procurement_directions")
    if not isinstance(directions, list):
        errors.append("procurement_directions must be a list")
        directions = []
    seen_products: set[str] = set()
    for index, direction in enumerate(directions):
        prefix = f"procurement_directions[{index}]"
        if not isinstance(direction, dict):
            errors.append(f"{prefix} must be an object")
            continue
        product = direction.get("product")
        if not isinstance(product, str) or not product.strip():
            errors.append(f"{prefix}.product must be non-empty")
            continue
        if product not in CATALOG_PRODUCTS:
            errors.append(f"{prefix}.product is not in the Aceler catalog")
        if product in seen_products:
            errors.append(f"duplicate procurement product: {product}")
        seen_products.add(product)
        if direction.get("priority") not in LEVELS:
            errors.append(f"{prefix}.priority must be 高, 中, or 低")
        if direction.get("evidence_status") not in EVIDENCE_STATES:
            errors.append(f"{prefix}.evidence_status is invalid")
        for field in ("application", "basis", "next_question"):
            if not str(direction.get(field, "")).strip():
                errors.append(f"{prefix}.{field} must be non-empty")
        check_evidence_ids(direction.get("evidence_ids"), source_ids, prefix, errors)

    if not directions and score >= 55:
        warnings.append("medium/high match has no procurement direction")
    if data.get("research_status") == "complete" and match.get("official_core_evidence") is False:
        warnings.append("research marked complete without official core evidence")
    if match.get("confidence") == "高" and (identity == "ambiguous" or match.get("official_core_evidence") is False):
        warnings.append("review high confidence with ambiguous identity or missing official core evidence")

    return {
        "valid": not errors,
        "raw_total": total,
        "score": score,
        "level": level,
        "errors": errors,
        "warnings": warnings,
    }


def check_evidence_ids(value: Any, source_ids: set[str], prefix: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{prefix}.evidence_ids must contain at least one source id")
        return
    for evidence_id in value:
        if evidence_id not in source_ids:
            errors.append(f"{prefix}.evidence_ids references unknown source id: {evidence_id}")


def make_case(*, high: bool = True, induction_graphite: bool = False) -> dict[str, Any]:
    process = "induction furnace" if induction_graphite else "EAF"
    product = "Graphite Electrode" if high or induction_graphite else "Wax for Precision Casting"
    return {
        "company": "Self Test Company",
        "identity_status": "confirmed",
        "research_status": "complete" if high else "partial",
        "company_positioning": {"text": "Test positioning.", "evidence_ids": ["S1"]},
        "role_judgment": {
            "operational_role": "终端用户" if high else "其他/公开资料不足",
            "commercial_relationship": "潜在客户" if high else "低匹配客户",
            "secondary_relationship": "",
            "reason": "Test role.",
            "evidence_ids": ["S1"],
        },
        "match": {
            "components": {
                "production_process_need": 28 if high else 8,
                "catalog_fit": 26 if high else 5,
                "consumption_intensity": 17 if high else 3,
                "demand_recurrence": 9 if high else 2,
                "company_role_fit": 8 if high else 2,
            },
            "only_industry_label": not high,
            "relevant_process_or_business_confirmed": high,
            "official_core_evidence": high,
            "sourcing_or_channel_signal_confirmed": high,
            "confidence": "高" if high else "低",
            "entry_barrier": "高" if high else "低",
            "rationale": "Self-test rationale.",
        },
        "confirmed_processes": [process] if high else [],
        "confirmed_lining_systems": [],
        "procurement_directions": [
            {
                "product": product,
                "priority": "高" if high else "低",
                "application": process if high else "unconfirmed",
                "evidence_status": "推测" if high else "公开资料未确认",
                "basis": "Self-test basis.",
                "evidence_ids": ["S1"],
                "next_question": "Confirm the application and specification.",
            }
        ],
        "sources": [{"id": "S1", "title": "Test source", "url": "https://example.com", "source_type": "官网"}],
    }


def self_test() -> int:
    high = validate(make_case(high=True))
    low = validate(make_case(high=False))
    semantic_case = validate(make_case(high=True, induction_graphite=True))
    new_product_case = make_case(high=False)
    new_product_case["procurement_directions"][0]["product"] = "Fumed Silica"
    new_product = validate(new_product_case)
    retired_product_case = make_case(high=False)
    retired_product_case["procurement_directions"][0]["product"] = "Ferro Silicon Nitride (HS Code 28500019)"
    retired_product = validate(retired_product_case)
    checks = [
        (high["valid"] and high["score"] == 85 and high["level"] == "高", "high EAF case"),
        (low["valid"] and low["score"] == 20 and low["level"] == "低", "low product-fit case"),
        (semantic_case["valid"], "business semantics are not a structural gate"),
        (new_product["valid"], "new catalog product case"),
        (not retired_product["valid"], "retired catalog product case"),
    ]
    failed = [name for passed, name in checks if not passed]
    result = {"valid": not failed, "tests": len(checks), "failed": failed}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", nargs="?", type=Path, help="Path to assessment JSON")
    parser.add_argument("--self-test", action="store_true", help="Run built-in test cases")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.assessment is None:
        parser.error("assessment is required unless --self-test is used")

    try:
        data = json.loads(args.assessment.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    if not isinstance(data, dict):
        print(json.dumps({"valid": False, "errors": ["assessment root must be an object"]}, ensure_ascii=False, indent=2))
        return 1

    result = validate(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
