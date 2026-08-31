#!/usr/bin/env python3
"""Company research pipeline with an optional read-only CRM sampler.

The reusable execution seam accepts a minimal identity seed, builds a trusted
AnySearch evidence pack, bounds Hermes calls, parses JSON, and runs the
repository validator.  CRM fields are never required by the research core.
"""

from __future__ import annotations

import argparse
import copy
import concurrent.futures
import html
import json
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse


TRIAL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TRIAL_DIR.parent
DEFAULT_ENV_FILE = PROJECT_DIR / "config" / "local.env"
DEFAULT_OUTPUT_ROOT = PROJECT_DIR / "outputs" / "company-research-trial"
DEFAULT_HERMES = Path.home() / ".local" / "bin" / "aceler-memory"
PROJECT_SKILL_DIR = PROJECT_DIR / "skill" / "aceler-company-research"
VALIDATOR = PROJECT_SKILL_DIR / "scripts" / "validate_assessment.py"
REPORT_CONTRACT = PROJECT_SKILL_DIR / "references" / "report-contract.md"
PRODUCT_CONTRACT = PROJECT_SKILL_DIR / "references" / "aceler-products.md"
ANYSEARCH_CLI = Path.home() / ".codex" / "skills" / "anysearch" / "scripts" / "anysearch_cli.js"
DEFAULT_TOOLSETS = "context_engine"
MAX_EVIDENCE_PAGES = 2
INDUSTRIES = (
    "GANG_TIE_YE_JIN",
    "NAI_HUO_CAI_LIAO",
    "ZHU_ZAO",
    "TAO_CI",
    "MO_LIAO",
    "SHE_BEI_GONG_CHENG",
    "MAO_YI_FEN_XIAO",
)


class AnySearchPackError(RuntimeError):
    """A bounded AnySearch failure."""


def resolved_validator() -> Path:
    """Use the validator versioned with this project."""
    return VALIDATOR


def hostname(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def _normalise_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed._replace(fragment="").geturl().rstrip("/")


def _provenance_url_key(value: str) -> tuple[str, str, str] | None:
    """Match harmless URL variants without admitting a different page."""
    normalized = _normalise_url(value)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = urlencode(
        [
            (name, value)
            for name, value in parse_qsl(parsed.query, keep_blank_values=True)
            if name.casefold() not in {"srsltid", "gclid", "fbclid"}
            and not name.casefold().startswith("utm_")
        ],
        doseq=True,
    )
    return host, path, query


def _trusted_url(url: str, company_domain: str | set[str]) -> bool:
    candidate = hostname(url)
    if not candidate:
        return False
    allowed = {company_domain} if isinstance(company_domain, str) else set(company_domain)
    allowed = {hostname(item) for item in allowed if hostname(item)}
    candidate = candidate.removeprefix("www.")
    allowed = {domain.removeprefix("www.") for domain in allowed}
    return any(candidate == domain or candidate.endswith(f".{domain}") for domain in allowed)


def load_env_file(path: Path) -> None:
    """Load simple KEY=value entries without evaluating shell code."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        try:
            values = shlex.split(raw_value, comments=True)
        except ValueError:
            continue
        os.environ.setdefault(key, values[0] if values else "")


def weakness_reasons(background: str | None) -> list[str]:
    text = (background or "").strip()
    reasons: list[str] = []
    if not text:
        return ["CRM 公司背景为空"]
    if len(text) < 80:
        reasons.append(f"CRM 公司背景过短（{len(text)} 字符）")
    elif len(text) < 300:
        reasons.append(f"CRM 公司背景较薄（{len(text)} 字符）")
    if not any(label in text for label in ("公司实质定位", "角色判断", "匹配度", "主要采购方向")):
        reasons.append("缺少标准化角色、匹配度和采购方向")
    if "http://" not in text and "https://" not in text:
        reasons.append("没有可核验来源链接")
    return reasons


def crm_connection():
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Missing psycopg. Run: python3 -m pip install -r requirements.txt") from exc
    required = ("TWENTY_DB_HOST", "TWENTY_DB_NAME", "TWENTY_DB_USER")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing CRM configuration: " + ", ".join(missing))
    return psycopg.connect(
        host=os.environ["TWENTY_DB_HOST"],
        port=int(os.getenv("TWENTY_DB_PORT", "5432")),
        dbname=os.environ["TWENTY_DB_NAME"],
        user=os.environ["TWENTY_DB_USER"],
        password=os.getenv("TWENTY_DB_PASSWORD"),
        sslmode=os.getenv("TWENTY_DB_SSLMODE", "prefer"),
        connect_timeout=int(os.getenv("TWENTY_DB_CONNECT_TIMEOUT", "5")),
    )


def read_candidates(limit: int) -> list[dict[str, Any]]:
    """Read weak-background companies through a parameterized, read-only query."""
    schema = os.getenv("TWENTY_WORKSPACE_SCHEMA", "").strip()
    if not schema:
        raise RuntimeError("Missing CRM configuration: TWENTY_WORKSPACE_SCHEMA")
    if not re.fullmatch(r"workspace_[a-z0-9]+", schema):
        raise RuntimeError(f"Invalid TWENTY_WORKSPACE_SCHEMA: {schema}")
    industry_sql = ", ".join("%s" for _ in INDUSTRIES)
    priority_sql = " ".join(
        f"WHEN '{industry}' THEN {index}" for index, industry in enumerate(INDUSTRIES, 1)
    )
    per_industry = max(1, math.ceil(limit / len(INDUSTRIES)))
    query = f'''
        WITH contact_counts AS (
          SELECT "companyId", count(*) FILTER (WHERE "deletedAt" IS NULL) AS contact_count
          FROM "{schema}".person GROUP BY "companyId"
        ), candidates AS (
          SELECT company.id::text AS id, company.name,
            company."domainNamePrimaryLinkUrl" AS website,
            company."linkedinLinkPrimaryLinkUrl" AS linkedin_url,
            company.industry::text AS industry, company.background,
            company."updatedAt" AS updated_at,
            COALESCE(contact_counts.contact_count, 0) AS contact_count,
            row_number() OVER (
              PARTITION BY company.industry::text
              ORDER BY CASE WHEN NULLIF(btrim(company.background), '') IS NULL THEN 0 ELSE 1 END,
                COALESCE(contact_counts.contact_count, 0) DESC,
                company."updatedAt" DESC, company.id::text
            ) AS industry_rank
          FROM "{schema}".company company
          LEFT JOIN contact_counts ON contact_counts."companyId" = company.id
          WHERE company."deletedAt" IS NULL
            AND company.industry::text IN ({industry_sql})
            AND NULLIF(btrim(company.name), '') IS NOT NULL
            AND NULLIF(btrim(company."domainNamePrimaryLinkUrl"), '') IS NOT NULL
            AND (NULLIF(btrim(company.background), '') IS NULL
              OR char_length(btrim(company.background)) < 300)
        )
        SELECT id, name, website, linkedin_url, industry, background, updated_at, contact_count
        FROM candidates
        WHERE industry_rank <= %s
        ORDER BY CASE industry {priority_sql} END, industry_rank LIMIT %s
    '''
    params = (*INDUSTRIES, per_industry, limit)
    with crm_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("BEGIN READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(query, params)
            columns = [column.name for column in cursor.description]
            rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
            cursor.execute("COMMIT")
    for row in rows:
        updated = row.get("updated_at")
        row["updated_at"] = updated.isoformat() if updated else None
        row["weakness_reasons"] = weakness_reasons(row.get("background"))
    return rows


def run_anysearch_cli(args: list[str], timeout: int = 90) -> str:
    """Run the configured AnySearch CLI without persisting credentials."""
    if not ANYSEARCH_CLI.is_file():
        raise AnySearchPackError(f"AnySearch CLI unavailable: {ANYSEARCH_CLI}")
    result = subprocess.run(
        ["node", str(ANYSEARCH_CLI), *args],
        cwd=PROJECT_DIR,
        env=child_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    output = result.stdout or ""
    if result.returncode:
        detail = (result.stderr or output or f"exit {result.returncode}").strip()
        raise AnySearchPackError(f"AnySearch command failed: {detail[-800:]}")
    if "auto_registered" in output and '"api_key"' in output:
        raise AnySearchPackError("AnySearch returned a new API key; refusing to save or use it")
    return output


def _clean_search_url(value: str) -> str:
    value = value.strip().strip("<>")
    value = value.rstrip(".,;:!?]}>'\"")
    return _normalise_url(value)


def _search_result_urls(search_output: str) -> list[str]:
    urls: list[str] = []
    for raw in re.findall(r"^- \*\*URL\*\*:\s*(https?://\S+)\s*$", search_output or "", flags=re.MULTILINE):
        url = _normalise_url(raw)
        if url and url not in urls:
            urls.append(url)
    for raw in re.findall(r"https?://[^\s<>\]\)\"']+", search_output or ""):
        url = _clean_search_url(raw)
        if url and url not in urls:
            urls.append(url)
    return urls


def _search_result_sections(search_output: str, limit: int) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for block in re.split(r"(?=^### \d+\.)", search_output or "", flags=re.MULTILINE):
        urls = _search_result_urls(block)
        if urls and len(block.strip()) >= 80:
            sections.append((urls[0], block.strip()))
        if len(sections) >= limit:
            break
    return sections


def _ranked_company_urls(search_output: str, name: str) -> list[str]:
    """Prefer company-specific product/process results over generic profiles."""
    ignored = {"company", "corporation", "limited", "ltd", "gmbh", "sdn", "bhd", "ctcp"}
    terms = [
        term.casefold()
        for term in re.findall(r"[^\W\d_]+", name)
        if len(term) > 2 and term.casefold() not in ignored
    ]
    process_terms = ("manufactur", "production", "product", "plant", "factory", "furnace", "kiln")
    ranked: list[tuple[tuple[int, int, int, int], int, str]] = []
    for order, (url, block) in enumerate(_search_result_sections(search_output, 50)):
        lowered = block.casefold()
        title = block.splitlines()[0].casefold()
        host = hostname(url).casefold()
        score = (
            sum(term in host for term in terms),
            sum(term in title for term in terms),
            sum(term in lowered for term in terms),
            sum(term in lowered for term in process_terms),
        )
        ranked.append((score, -order, url))
    ranked.sort(reverse=True)
    urls: list[str] = []
    seen: set[tuple[str, str]] = set()
    for _, _, url in ranked:
        parsed = urlparse(url)
        key = (hostname(url).removeprefix("www."), parsed.path.rstrip("/") or "/")
        if key in seen:
            continue
        seen.add(key)
        urls.append(url)
    return urls or _search_result_urls(search_output)


def _substantive_extract(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 80:
        return False
    lowered = stripped.lower()
    return not any(
        lowered.startswith(marker)
        for marker in ("error", "api key", "not found", "unauthorized", "extract_invalid_content")
    )


def _identity_seed_name(value: Any) -> str:
    value = re.sub(r"[\r\n]+", " ", str(value or "")).replace('"', "")
    value = re.sub(r"(?i)\bsite\s*:", "", value)
    return re.sub(r"\s+", " ", value).strip()[:120]


def _extract_title(text: str, url: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            title = line.lstrip("# ").strip()
            if title:
                return title[:240]
    return url


def anysearch_pack(record: dict[str, Any], max_sources: int = MAX_EVIDENCE_PAGES) -> tuple[str, dict[str, Any]]:
    """Collect identity and process evidence, preferring the company domain."""
    name = str(record.get("name") or "").strip()
    seed_url = _normalise_url(str(record.get("website") or ""))
    domain = hostname(seed_url)
    if not name:
        raise AnySearchPackError("Input identity seed has no company name")
    max_sources = max(1, min(MAX_EVIDENCE_PAGES, int(max_sources)))
    identity_seed = " ".join(part for part in (_identity_seed_name(name), domain) if part)
    queries = [
        f'"{identity_seed}" official website products company',
        f'"{identity_seed}" manufacturing plant process furnace kiln',
    ]
    metadata: dict[str, Any] = {
        "query": " | ".join(queries),
        "queries": queries,
        "selected_urls": [],
        "extracted_urls": [],
        "search_calls": 0,
        "extract_calls": 0,
        "external_fallback": False,
        "seconds": 0.0,
    }
    started = time.monotonic()
    try:
        search_output = run_anysearch_cli(
            ["batch_search", "--query", queries[0], "--query", queries[1], "--max_results", "5"],
            timeout=20,
        )
        metadata["search_calls"] = 1
    except Exception as exc:
        metadata["error"] = str(exc)
        search_output = ""
    candidates = [*([seed_url] if seed_url else []), *_search_result_urls(search_output)]
    trusted: list[str] = []
    for candidate in candidates:
        candidate = _normalise_url(candidate)
        if domain and candidate and _trusted_url(candidate, domain) and candidate not in trusted:
            trusted.append(candidate)
    pages: list[tuple[str, str]] = []
    for url in trusted:
        if len(pages) >= max_sources:
            break
        try:
            extracted = run_anysearch_cli(["extract", url], timeout=15)
            metadata["extract_calls"] += 1
        except Exception:
            continue
        if _substantive_extract(extracted):
            pages.append((url, extracted.strip()))
            metadata["extracted_urls"].append(url)
    if domain and not pages:
        supplemental_queries = [
            f'"{_identity_seed_name(name)}" "{domain}" products manufacturing plant',
            f'"{_identity_seed_name(name)}" "{domain}" furnace kiln smelter foundry refractory ceramic abrasive',
        ]
        metadata["supplemental_queries"] = supplemental_queries
        try:
            supplemental_output = run_anysearch_cli(
                ["batch_search", "--query", supplemental_queries[0], "--query", supplemental_queries[1], "--max_results", "5"],
                timeout=20,
            )
            metadata["search_calls"] += 1
            metadata["supplemental_search"] = True
            search_output = "\n".join(part for part in (search_output, supplemental_output) if part)
            for url in (_normalise_url(item) for item in _ranked_company_urls(supplemental_output, name)):
                duplicate = any(
                    hostname(existing).removeprefix("www.") == hostname(url).removeprefix("www.")
                    and (urlparse(existing).path.rstrip("/") or "/") == (urlparse(url).path.rstrip("/") or "/")
                    for existing, _ in pages
                )
                if not url or not _trusted_url(url, domain) or duplicate:
                    continue
                if len(pages) >= max_sources:
                    break
                try:
                    extracted = run_anysearch_cli(["extract", url], timeout=15)
                    metadata["extract_calls"] += 1
                except Exception:
                    continue
                if _substantive_extract(extracted):
                    pages.append((url, extracted.strip()))
                    metadata["extracted_urls"].append(url)
        except Exception as exc:
            metadata["supplemental_error"] = str(exc)
    if not pages:
        metadata["external_fallback"] = True
        for url in (_normalise_url(item) for item in _ranked_company_urls(search_output, name)):
            if not url or url in trusted or any(existing == url for existing, _ in pages):
                continue
            if len(pages) >= max_sources:
                break
            try:
                extracted = run_anysearch_cli(["extract", url], timeout=15)
                metadata["extract_calls"] += 1
            except Exception:
                continue
            if _substantive_extract(extracted):
                pages.append((url, extracted.strip()))
                metadata["extracted_urls"].append(url)
    if not pages:
        pages = _search_result_sections(search_output, max_sources)
        metadata["search_snippet_fallback"] = True
    metadata["selected_urls"] = [url for url, _ in pages]
    metadata["seconds"] = round(time.monotonic() - started, 1)
    if not pages:
        raise AnySearchPackError("AnySearch found no trusted substantive company page")
    sections = ["# AnySearch extracted identity-seeded sources"]
    for index, (url, text) in enumerate(pages, 1):
        sections.extend(["", f"## S{index}", f"URL: {url}", f"Title: {_extract_title(text, url)}", "", text])
    return "\n".join(sections).strip() + "\n", metadata


def extract_json_object(raw: str) -> dict[str, Any]:
    """Parse one object, preferring the sole fenced JSON block when present."""
    text = (raw or "").strip()
    fenced = re.findall(r"```json\s*\n?(.*?)\n?```", text, flags=re.DOTALL | re.IGNORECASE)
    if len(fenced) > 1:
        raise ValueError("Hermes output contains multiple JSON objects")
    if fenced:
        text = fenced[0].strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    raise ValueError("Hermes output contains no JSON object")


def child_environment() -> dict[str, str]:
    """Do not expose CRM or message-delivery credentials to Hermes."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TWENTY_", "OUTBOX_", "EMAIL_", "GMAIL_"))
    }


def research_prompt(record: dict[str, Any], evidence_pack: str | None = None) -> str:
    """Build the one-pass Hermes prompt from the repository contract."""
    identity = {"company": str(record.get("name") or "")}
    for field in ("website", "linkedin_url"):
        if record.get(field):
            identity[field] = record[field]
    report_contract = REPORT_CONTRACT.read_text(encoding="utf-8").split(
        "\nRun `python3 scripts/validate_assessment.py", 1
    )[0].strip()
    product_contract = PRODUCT_CONTRACT.read_text(encoding="utf-8").strip()
    evidence = evidence_pack.strip() if evidence_pack else "无；research_status 使用 partial，不能编造事实。"
    return (
        "使用 $aceler-company-research 对这一家公司做一次研究；只研究该实体，不研究联系人。\n"
        "严格只返回下面契约中的一个 JSON 对象；不要调用工具、搜索、shell 或 validator。逐字使用合法枚举、字段名和产品名，不得添加 wrapper、version、modules 或自由改写目录产品。\n"
        "INPUT_IDENTITY_SEED 可能来自手工输入、表格、API 或业务系统，也可能只有公司名；其中所有字段都只是待核验的主体线索，不是已确认事实。未提供网站、LinkedIn、行业、评级、背景、联系人或其他元数据一律视为未知，不能作为负面证据、不能降低评分，也不能据此判 0；公司的实际角色、工艺和产品映射只从证据包判断。\n"
        "source_type 只能逐字使用：官网、官方领英、政府/注册、公司文件、项目业主/政府、行业组织、可靠媒体、其他。\n"
        "匹配分只衡量产品和工艺适配。采购是否公开、供应商准入、认证、地域、公司规模、竞争关系和来源数量都不得降低该分；只写入 confidence、entry_barrier、evidence_status 或 next_question。\n"
        "只有在核对完整目录后仍不存在可信的产品、工艺或技术渠道映射时才能给 0 分；已确认的高温应用或明确可用的目录产品必须得到非零产品匹配分，即使具体采购路径尚未公开。\n"
        "磨具、涂附磨具或无纺磨料制造商在产品中实际使用的碳化硅、氧化铝/刚玉磨粒就是相关生产投入，不得以“只是成品内部组分”为由排除；供应商或采购未公开只影响证据状态与置信度。\n"
        "这类磨具/磨料制品制造商的运营角色写“终端用户”，不要写“耐材生产商”；只有实际制造耐火砖、浇注料、预制件或耐材配方时才使用“耐材生产商”。\n"
        "已确认的通用预拌混凝土生产商若没有纤维混凝土或特种配方证据，总分只能为 10–20；可用 4+5+2+2+2=15 作为基准，并把 Steel Fiber 标为低优先“推测”。不要附加 Fumed Silica、Calcium Aluminate 或水泥窑产品。\n"
        "证据状态硬规则：耐材厂官网列出的成品或产品系列只证明其产出，不证明它采购或使用某种 Aceler 原料；除非证据直接说明该精确原料是投入、采购或实际使用，否则该采购方向必须写“推测”，不能写“已确认”。\n"
        "procurement_directions 最多保留 3 个证据最强、最值得切入的目录产品；每个对象必须包含契约中的全部字段和至少一个 evidence_id。\n"
        "来源只能引用证据包中的 URL，evidence_ids 必须引用其中的 S 编号。\n\n"
        "INPUT_IDENTITY_SEED:\n" + json.dumps(identity, ensure_ascii=False) + "\n\n"
        "REPORT_CONTRACT（运行时唯一 schema 与评分规则）:\n---BEGIN REPORT CONTRACT---\n"
        + report_contract
        + "\n---END REPORT CONTRACT---\n\n"
        "PRODUCT_CONTRACT（运行时唯一产品目录与工艺映射）:\n---BEGIN PRODUCT CONTRACT---\n"
        + product_contract
        + "\n---END PRODUCT CONTRACT---\n\n"
        "ANYSEARCH_EVIDENCE_PACK:\n---BEGIN EVIDENCE---\n" + evidence + "\n---END EVIDENCE---\n\n"
        "FINAL_OUTPUT_LANGUAGE：返回前检查公司定位、角色理由、评分依据、流程/衬里说明及采购方向的用途、依据和下一步问题；除公司/人名、品牌、目录产品、牌号、工艺缩写、数字和单位外，所有展示性自由文本必须使用简洁、自然的中文。字段名、枚举、URL 和 evidence_id 不得翻译。只返回 JSON。"
    )


def zero_score_review_prompt(base_prompt: str, prior_assessment: dict[str, Any]) -> str:
    """Ask once whether a valid zero overlooked a product, process, or channel route."""
    return (
        base_prompt
        + "\n\n这是一次仅针对首次合法结果为 0% 的独立复核，不是格式重试，也不得再次搜索。\n"
        "只使用同一份 ANYSEARCH_EVIDENCE_PACK 和上次 JSON，逐项复查四类可能性："
        "耐材制造及其技术上可映射的原料；铸造、熔炼及其炉衬/高温耗材；"
        "工程安装、材料交付、规格控制、贸易或分销渠道；其他直接生产投入。\n"
        "证据已确认上述耐材制造、铸造/熔炼或相关工程/分销渠道时，必须体现为非零的对应工艺或渠道匹配；精确产品仍须按证据限定。"
        "不得把‘该公司的产出不在 Aceler 目录’等同于‘其生产工艺不消耗 Aceler 产品’。"
        "输入线索缺字段、供应商/采购记录未公开、炉型或配方细节未公开，都不能单独作为降低产品/工艺匹配分或维持 0% 的理由；应转入置信度、证据状态和下一步问题。"
        "但金刚石、CBN、硬质合金或工具销售等超硬材料邻接关系本身不证明其使用 Silicon Carbide、Brown Fused Alumina 或 White Fused Alumina；没有公司级磨粒/工艺证据时不得加分。"
        "证据不足时必须维持 0%，不得为了提高分数编造工艺、采购或渠道关系。\n"
        "只返回一个符合原契约的完整 JSON 对象；若维持 0%，也返回完整对象并在 rationale 中说明。\n\n"
        "上次已通过校验的 JSON：\n"
        + json.dumps(prior_assessment, ensure_ascii=False)
    )


def _redact_sensitive(text: str) -> str:
    for name in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "ANYSEARCH_API_KEY"):
        value = os.getenv(name)
        if value:
            text = text.replace(value, "[redacted]")
    return re.sub(r"(?i)(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)


def _invoke_hermes(
    *,
    record_dir: Path,
    hermes: Path,
    timeout: int,
    reasoning: str,
    prompt: str,
    toolsets: str = DEFAULT_TOOLSETS,
    usage_path: Path | None = None,
    raw_path: Path | None = None,
    attempt_kind: str = "research",
) -> dict[str, Any]:
    """Invoke Hermes once and retain its raw, redacted output."""
    started = time.monotonic()
    usage_path = usage_path or record_dir / "hermes-usage.json"
    raw_path = raw_path or record_dir / "hermes-raw.txt"
    command = [
        str(hermes),
        "--reasoning",
        reasoning,
        "--ignore-rules",
        "--toolsets",
        toolsets,
        "--usage-file",
        str(usage_path),
        "--oneshot",
        prompt,
    ]
    errors: list[str] = []
    raw = ""
    returncode: int | None = None
    usage: dict[str, Any] | None = None
    try:
        usage_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        result = subprocess.run(
            command,
            cwd=record_dir,
            env=child_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        returncode = result.returncode
        raw = _redact_sensitive(result.stdout or "")
        if result.returncode:
            detail = _redact_sensitive(result.stderr or raw or f"exit {result.returncode}")
            errors.append(detail[-1000:])
    except subprocess.TimeoutExpired:
        errors.append(f"Hermes timed out after {timeout}s")
    except OSError as exc:
        errors.append(f"Hermes invocation failed: {type(exc).__name__}: {exc}")
    try:
        raw_path.write_text(raw, encoding="utf-8")
    except OSError as exc:
        errors.append(f"raw output write failed: {type(exc).__name__}: {exc}")
    if usage_path.is_file():
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            usage = None
    assessment: dict[str, Any] | None = None
    if returncode == 0:
        try:
            assessment = extract_json_object(raw)
        except ValueError as exc:
            errors.append(str(exc))
    return {
        "assessment": assessment,
        "raw": raw,
        "errors": errors,
        "usage": usage,
        "seconds": round(time.monotonic() - started, 1),
        "attempt": {
            "kind": attempt_kind,
            "returncode": returncode,
            "has_json": assessment is not None,
            "seconds": round(time.monotonic() - started, 1),
        },
    }


def _translation_payload(assessment: dict[str, Any]) -> dict[str, Any]:
    directions = assessment.get("procurement_directions") or []
    return {
        "company_positioning": str((assessment.get("company_positioning") or {}).get("text") or ""),
        "role_reason": str((assessment.get("role_judgment") or {}).get("reason") or ""),
        "match_rationale": str((assessment.get("match") or {}).get("rationale") or ""),
        "confirmed_processes": [str(value) for value in assessment.get("confirmed_processes") or []],
        "confirmed_lining_systems": [str(value) for value in assessment.get("confirmed_lining_systems") or []],
        "procurement_directions": [
            {
                "application": str(direction.get("application") or ""),
                "basis": str(direction.get("basis") or ""),
                "next_question": str(direction.get("next_question") or ""),
            }
            for direction in directions
            if isinstance(direction, dict)
        ],
    }


def _same_text_shape(template: Any, candidate: Any) -> bool:
    if isinstance(template, str):
        return isinstance(candidate, str)
    if isinstance(template, list):
        return isinstance(candidate, list) and len(template) == len(candidate) and all(
            _same_text_shape(left, right) for left, right in zip(template, candidate)
        )
    if isinstance(template, dict):
        return isinstance(candidate, dict) and set(template) == set(candidate) and all(
            _same_text_shape(template[key], candidate[key]) for key in template
        )
    return False


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    return []


def _apply_translation(assessment: dict[str, Any], translated: dict[str, Any]) -> dict[str, Any]:
    localized = copy.deepcopy(assessment)
    localized["company_positioning"]["text"] = translated["company_positioning"]
    localized["role_judgment"]["reason"] = translated["role_reason"]
    localized["match"]["rationale"] = translated["match_rationale"]
    localized["confirmed_processes"] = translated["confirmed_processes"]
    localized["confirmed_lining_systems"] = translated["confirmed_lining_systems"]
    for direction, localized_text in zip(
        localized.get("procurement_directions") or [], translated["procurement_directions"]
    ):
        direction.update(localized_text)
    return localized


def localize_item(item: dict[str, Any], hermes: Path, timeout: int, reasoning: str) -> dict[str, Any]:
    """Add a fail-open Chinese display copy after canonical research is complete."""
    assessment = item.get("assessment")
    record_dir_value = item.get("record_dir")
    if item.get("status") != "valid" or not isinstance(assessment, dict) or not record_dir_value:
        item["translation"] = {"status": "skipped", "errors": []}
        return item
    record_dir = Path(str(record_dir_value))
    payload = _translation_payload(assessment)
    protected = {
        str(assessment.get("company") or "").strip(),
        *{
            str(direction.get("product") or "").strip()
            for direction in assessment.get("procurement_directions") or []
            if isinstance(direction, dict)
        },
    }
    protected.discard("")
    source_text = "\n".join(_text_values(payload))
    protected.update(re.findall(r"\b[A-Z][A-Z0-9.-]{1,}\b", source_text))
    protected.update(
        re.findall(r"\b(?:[A-Z][a-z]+(?:[-'][A-Za-z]+)?\s+){1,3}[A-Z][a-z]+(?:[-'][A-Za-z]+)?\b", source_text)
    )
    remaining_text = source_text
    for term in sorted(protected, key=len, reverse=True):
        remaining_text = remaining_text.replace(term, "")
    if not re.search(r"[A-Za-z]{3,}", remaining_text):
        item["translation"] = {"status": "not_needed", "errors": []}
        return item
    prompt = (
        "把下面 JSON 中的英文说明翻译成简洁、自然的中文。只做翻译，不核查、不补充、不删除、不改写事实。\n"
        "严格保留公司名、人名、品牌名、产品专名、材料牌号、工艺缩写、数字、单位和引号中的原词；已有中文保持不变。\n"
        "只返回键、数组长度和结构完全相同的一个 JSON 对象，不要使用工具，不要输出解释。\n"
        "必须逐字保留的词：" + json.dumps(sorted(protected), ensure_ascii=False) + "\n\n"
        "待翻译 JSON：\n" + json.dumps(payload, ensure_ascii=False)
    )
    try:
        invocation = _invoke_hermes(
            record_dir=record_dir,
            hermes=hermes,
            timeout=timeout,
            reasoning=reasoning,
            prompt=prompt,
            toolsets=DEFAULT_TOOLSETS,
            usage_path=record_dir / "hermes-usage-translation.json",
            raw_path=record_dir / "hermes-raw-translation.txt",
            attempt_kind="translation",
        )
        translated = invocation.get("assessment")
        translation_errors = [str(error) for error in invocation.get("errors") or []]
        if not isinstance(translated, dict) or not _same_text_shape(payload, translated):
            translation_errors.append("Translation output changed the JSON shape")
        if isinstance(translated, dict) and _same_text_shape(payload, translated):
            for source, target in zip(_text_values(payload), _text_values(translated)):
                if source.strip() and not target.strip():
                    translation_errors.append("Translation removed non-empty text")
                for term in protected:
                    if term in source and term not in target:
                        translation_errors.append(f"Translation changed protected term: {term}")
        if translation_errors:
            item["translation"] = {
                "status": "failed",
                "errors": list(dict.fromkeys(translation_errors)),
                "usage": invocation.get("usage"),
                "seconds": invocation.get("seconds"),
            }
            (record_dir / "result.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return item
        display_assessment = _apply_translation(assessment, translated)
        item["display_assessment"] = display_assessment
        item["translation"] = {
            "status": "applied",
            "errors": [],
            "usage": invocation.get("usage"),
            "seconds": invocation.get("seconds"),
        }
        (record_dir / "localized-assessment.json").write_text(
            json.dumps(display_assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (record_dir / "result.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # The display adapter must never change research success.
        item.pop("display_assessment", None)
        item["translation"] = {
            "status": "failed",
            "errors": [_redact_sensitive(f"{type(exc).__name__}: {exc}")],
        }
    return item


def validate_assessment(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(resolved_validator()), str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"valid": False, "score": 0, "level": "低", "errors": ["Validator returned invalid JSON"], "warnings": []}
    if not isinstance(parsed, dict):
        return {"valid": False, "score": 0, "level": "低", "errors": ["Validator returned a non-object"], "warnings": []}
    return parsed


def _validate_object(data: dict[str, Any], directory: Path) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", dir=directory, delete=True) as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        return validate_assessment(Path(handle.name))


def _pack_urls(evidence_pack: str | None) -> set[str]:
    urls = re.findall(r"(?im)^URL:\s*(https?://\S+)", evidence_pack or "")
    return {_normalise_url(url) for url in urls if _normalise_url(url)}


def anysearch_source_errors(assessment: dict[str, Any], evidence_pack: str | None) -> list[str]:
    """Keep assessment provenance inside the trusted AnySearch boundary."""
    trusted = {_provenance_url_key(url) for url in _pack_urls(evidence_pack)}
    trusted.discard(None)
    errors: list[str] = []
    sources = assessment.get("sources")
    if not isinstance(sources, list):
        return errors
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        key = _provenance_url_key(url)
        if key and key not in trusted:
            errors.append(f"sources[{index}].url is not in the trusted AnySearch evidence pack")
    return errors


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return value[:48] or "company"


def _record_dir(record: dict[str, Any], index: int, run_dir: Path) -> Path:
    return run_dir / "records" / f"{index:03d}-{_slug(str(record.get('id') or record.get('name') or 'company'))}"


def research_one(
    record: dict[str, Any],
    index: int,
    run_dir: Path,
    hermes: Path = DEFAULT_HERMES,
    timeout: int = 300,
    reasoning: str = "medium",
    evidence_pack: str | None = None,
    toolsets: str = DEFAULT_TOOLSETS,
    use_anysearch: bool = True,
    max_attempts: int = 3,
    review_zero_score: bool = True,
) -> dict[str, Any]:
    """Run one company, reusing its evidence across bounded Hermes retries."""
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    started = time.monotonic()
    record_dir = _record_dir(record, index, run_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    search_meta: dict[str, Any] = {"selected_urls": [], "search_calls": 0, "extract_calls": 0, "seconds": 0.0}
    errors: list[str] = []
    if evidence_pack is None and use_anysearch:
        try:
            evidence_pack, search_meta = anysearch_pack(record)
            (record_dir / "anysearch-evidence.md").write_text(evidence_pack, encoding="utf-8")
            (record_dir / "anysearch-meta.json").write_text(json.dumps(search_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            errors.append(str(exc))
            evidence_pack = ""
    elif evidence_pack:
        (record_dir / "anysearch-evidence.md").write_text(evidence_pack, encoding="utf-8")
    if not evidence_pack.strip() or not _pack_urls(evidence_pack):
        errors.append("No trusted AnySearch evidence pack; Hermes was not called")
        validation = {
            "valid": False,
            "score": 0,
            "level": "低",
            "errors": list(dict.fromkeys(errors)),
            "warnings": [],
        }
        result = {
            "index": index,
            "record": record,
            "status": "failed",
            "assessment": None,
            "validation": validation,
            "errors": validation["errors"],
            "duration_seconds": round(time.monotonic() - started, 1),
            "usage": None,
            "anysearch": search_meta,
            "research": {"kind": "not_started", "has_json": False},
            "record_dir": str(record_dir),
        }
        (record_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    base_prompt = research_prompt(record, evidence_pack)
    attempts: list[dict[str, Any]] = []
    retry_errors: list[str] = []
    invocation: dict[str, Any] = {}
    assessment: dict[str, Any] | None = None
    validation: dict[str, Any] = {}
    status = "failed"
    zero_score_review: dict[str, Any] = {
        "enabled": review_zero_score,
        "triggered": False,
        "accepted": False,
        "changed_score": False,
        "initial_score": None,
        "review_score": None,
        "errors": [],
    }
    for attempt_number in range(1, max_attempts + 1):
        prompt = base_prompt
        if retry_errors:
            detail = "\n".join(f"- {error}" for error in retry_errors)[:2000]
            prompt += (
                "\n\n上次输出未通过校验。只修正 JSON 结构、合法枚举和证据引用，不改变已由证据支持的事实；仍只返回一个 JSON 对象。\n"
                + detail
            )
        invocation = _invoke_hermes(
            record_dir=record_dir,
            hermes=hermes,
            timeout=timeout,
            reasoning=reasoning,
            prompt=prompt,
            toolsets=toolsets,
            usage_path=record_dir / f"hermes-usage-attempt-{attempt_number}.json",
            raw_path=record_dir / f"hermes-raw-attempt-{attempt_number}.txt",
            attempt_kind=f"research_attempt_{attempt_number}",
        )
        attempt_errors = [str(error) for error in invocation.get("errors") or []]
        assessment = invocation.get("assessment")
        if isinstance(assessment, dict):
            validation = _validate_object(assessment, record_dir)
            provenance_errors = anysearch_source_errors(assessment, evidence_pack)
            if provenance_errors:
                validation["valid"] = False
                validation["errors"] = list(validation.get("errors") or []) + provenance_errors
            if not validation.get("valid"):
                attempt_errors.extend(str(error) for error in validation.get("errors") or [])
        else:
            validation = {
                "valid": False,
                "score": 0,
                "level": "低",
                "errors": ["Hermes output contains no valid assessment JSON"],
                "warnings": [],
            }
            attempt_errors.extend(validation["errors"])
        attempt_errors = list(dict.fromkeys(attempt_errors))
        attempts.append(
            {
                **(invocation.get("attempt") or {}),
                "number": attempt_number,
                "errors": attempt_errors,
                "validation": {
                    key: validation.get(key) for key in ("valid", "score", "level", "errors", "warnings")
                },
                "usage": invocation.get("usage"),
            }
        )
        status = "valid" if isinstance(assessment, dict) and validation.get("valid") and not attempt_errors else "failed"
        retry_errors = attempt_errors
        if status == "valid":
            break
    if status == "valid" and review_zero_score and validation.get("score") == 0:
        zero_score_review["triggered"] = True
        zero_score_review["initial_score"] = 0
        review_invocation = _invoke_hermes(
            record_dir=record_dir,
            hermes=hermes,
            timeout=timeout,
            reasoning=reasoning,
            prompt=zero_score_review_prompt(base_prompt, assessment),
            toolsets=toolsets,
            usage_path=record_dir / "hermes-usage-zero-review.json",
            raw_path=record_dir / "hermes-raw-zero-review.txt",
            attempt_kind="zero_score_review",
        )
        review_errors = [str(error) for error in review_invocation.get("errors") or []]
        review_assessment = review_invocation.get("assessment")
        if isinstance(review_assessment, dict):
            review_validation = _validate_object(review_assessment, record_dir)
            provenance_errors = anysearch_source_errors(review_assessment, evidence_pack)
            if provenance_errors:
                review_validation["valid"] = False
                review_validation["errors"] = list(review_validation.get("errors") or []) + provenance_errors
            if not review_validation.get("valid"):
                review_errors.extend(str(error) for error in review_validation.get("errors") or [])
        else:
            review_validation = {
                "valid": False,
                "score": 0,
                "level": "低",
                "errors": ["Hermes zero-score review contains no valid assessment JSON"],
                "warnings": [],
            }
            review_errors.extend(review_validation["errors"])
        review_errors = list(dict.fromkeys(review_errors))
        review_accepted = isinstance(review_assessment, dict) and review_validation.get("valid") and not review_errors
        attempts.append(
            {
                **(review_invocation.get("attempt") or {}),
                "number": len(attempts) + 1,
                "errors": review_errors,
                "validation": {
                    key: review_validation.get(key) for key in ("valid", "score", "level", "errors", "warnings")
                },
                "usage": review_invocation.get("usage"),
            }
        )
        zero_score_review.update(
            {
                "accepted": bool(review_accepted),
                "changed_score": bool(review_accepted and review_validation.get("score") != 0),
                "review_score": review_validation.get("score") if review_accepted else None,
                "errors": review_errors,
            }
        )
        if review_accepted:
            invocation = review_invocation
            assessment = review_assessment
            validation = review_validation
    errors = [] if status == "valid" else retry_errors
    (record_dir / "hermes-raw.txt").write_text(str(invocation.get("raw") or ""), encoding="utf-8")
    if isinstance(invocation.get("usage"), dict):
        (record_dir / "hermes-usage.json").write_text(
            json.dumps(invocation["usage"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if status == "valid":
        (record_dir / "accepted-assessment.json").write_text(json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "index": index,
        "record": record,
        "status": status,
        "assessment": assessment if isinstance(assessment, dict) else None,
        "validation": validation,
        "errors": list(dict.fromkeys(errors)),
        "duration_seconds": round(time.monotonic() - started, 1),
        "usage": invocation.get("usage"),
        "anysearch": search_meta,
        "research": {
            **(invocation.get("attempt") or {}),
            "attempt_count": len(attempts),
            "max_attempts": max_attempts,
            "attempts": attempts,
            "zero_score_review": zero_score_review,
        },
        "record_dir": str(record_dir),
    }
    (record_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def markdown_link(source: dict[str, Any]) -> str:
    title = str(source.get("title") or source.get("url") or "来源")
    url = str(source.get("url") or "")
    return f"[{title}]({url})" if url.startswith(("http://", "https://")) else title


def evidence_links(assessment: dict[str, Any], ids: list[str]) -> str:
    sources = {source.get("id"): source for source in assessment.get("sources") or [] if isinstance(source, dict)}
    return "；".join(markdown_link(sources[source_id]) for source_id in ids if source_id in sources)


def render_assessment(assessment: dict[str, Any], validation: dict[str, Any]) -> str:
    positioning = assessment.get("company_positioning") or {}
    role = assessment.get("role_judgment") or {}
    match = assessment.get("match") or {}
    lines = [
        "## 公司实质定位",
        "",
        str(positioning.get("text") or "未填写") + (f" 来源：{evidence_links(assessment, positioning.get('evidence_ids') or [])}" if positioning.get("evidence_ids") else ""),
        "",
        "## 角色判断",
        "",
        f"- 运营角色：{role.get('operational_role') or '未判断'}",
        f"- 对 Aceler 的关系：{role.get('commercial_relationship') or '未判断'}",
        f"- 判断：{role.get('reason') or '未填写'}",
        "",
        "## 匹配度",
        "",
        f"- {validation.get('level', '低')}（约 {validation.get('score', 0)}%）",
        f"- 证据置信度：{match.get('confidence') or '未确认'}",
        f"- 进入门槛：{match.get('entry_barrier') or '未确认'}",
        f"- 评分依据：{match.get('rationale') or '未填写'}",
        "",
        "## 主要采购方向",
        "",
    ]
    directions = assessment.get("procurement_directions") or []
    if directions:
        lines.extend(["| 优先级 | Aceler 产品 | 对应流程/用途 | 依据状态 | 下一步确认 |", "|---|---|---|---|---|"])
        for direction in directions:
            lines.append(
                "| " + " | ".join(
                    str(direction.get(field) or "").replace("|", "\\|")
                    for field in ("priority", "product", "application", "evidence_status", "next_question")
                ) + " |"
            )
    else:
        lines.append("没有足够证据支持具体采购方向。")
    return "\n".join(lines) + "\n"


def source_links_html(assessment: dict[str, Any], ids: list[str]) -> str:
    sources = {source.get("id"): source for source in assessment.get("sources") or [] if isinstance(source, dict)}
    links: list[str] = []
    for source_id in ids:
        source = sources.get(source_id)
        if not source:
            continue
        url = str(source.get("url") or "")
        title = html.escape(str(source.get("title") or url))
        if url.startswith(("http://", "https://")):
            links.append(f"<a href=\"{html.escape(url, quote=True)}\" target=\"_blank\" rel=\"noopener\">{title}</a>")
    return "；".join(links) or "未提供"


def render_assessment_html(assessment: dict[str, Any], validation: dict[str, Any]) -> str:
    positioning = assessment.get("company_positioning") or {}
    role = assessment.get("role_judgment") or {}
    match = assessment.get("match") or {}
    parts = [
        f"<section><h3>公司实质定位</h3><p>{html.escape(str(positioning.get('text') or '未填写'))}</p><p>来源：{source_links_html(assessment, positioning.get('evidence_ids') or [])}</p></section>",
        f"<section><h3>角色判断</h3><p>运营角色：{html.escape(str(role.get('operational_role') or '未判断'))}<br>对 Aceler 的关系：{html.escape(str(role.get('commercial_relationship') or '未判断'))}</p><p>{html.escape(str(role.get('reason') or '未填写'))}</p><p>来源：{source_links_html(assessment, role.get('evidence_ids') or [])}</p></section>",
        f"<section><h3>匹配度</h3><p><strong>{html.escape(str(validation.get('level') or '低'))}（约 {html.escape(str(validation.get('score', 0)))}%）</strong><br>证据置信度：{html.escape(str(match.get('confidence') or '未确认'))}<br>进入门槛：{html.escape(str(match.get('entry_barrier') or '未确认'))}</p><p>{html.escape(str(match.get('rationale') or '未填写'))}</p></section>",
    ]
    directions = assessment.get("procurement_directions") or []
    if directions:
        rows = []
        for direction in directions:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(direction.get('priority') or ''))}</td>"
                f"<td>{html.escape(str(direction.get('product') or ''))}</td>"
                f"<td>{html.escape(str(direction.get('application') or ''))}<br>{html.escape(str(direction.get('basis') or ''))}<br>来源：{source_links_html(assessment, direction.get('evidence_ids') or [])}</td>"
                f"<td>{html.escape(str(direction.get('evidence_status') or ''))}</td>"
                f"<td>{html.escape(str(direction.get('next_question') or ''))}</td></tr>"
            )
        procurement = "<section><h3>主要采购方向</h3><table><thead><tr><th>优先级</th><th>Aceler 产品</th><th>对应流程/依据</th><th>依据状态</th><th>下一步确认</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></section>"
    else:
        procurement = "<section><h3>主要采购方向</h3><p>没有足够证据支持具体采购方向。</p></section>"
    return "".join(parts) + procurement


def original_markdown(record: dict[str, Any]) -> str:
    lines = [f"- 公司名：{record.get('name') or '未填写'}"]
    optional_fields = (
        ("行业", "industry"),
        ("官网", "website"),
        ("LinkedIn", "linkedin_url"),
        ("关联联系人数量", "contact_count"),
    )
    for label, field in optional_fields:
        if field in record and record.get(field) not in (None, ""):
            lines.append(f"- {label}：{record[field]}")
    if record.get("weakness_reasons"):
        lines.append(f"- 入选原因：{'；'.join(record['weakness_reasons'])}")
    if record.get("background"):
        lines.extend(["", "提供的背景（仅作待核验线索）：", "", "> " + str(record["background"]).replace("\n", "\n> ")])
    return "\n".join(lines)


def write_reports(run_dir: Path, items: list[dict[str, Any]]) -> tuple[Path, Path]:
    valid = sum(item.get("status") == "valid" for item in items)
    failed = len(items) - valid
    lines = [
        "# 输入记录与 Hermes 背调对照",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        "- 输入字段：公司名必填，其他字段可选且仅作待核验线索",
        f"- 样本：{len(items)} 家；有效：{valid}；失败：{failed}",
        "",
        "| # | 公司 | 输入行业 | Hermes 角色 | 匹配度 | 状态 |",
        "|---:|---|---|---|---:|---|",
    ]
    for item in items:
        record = item["record"]
        assessment = item.get("display_assessment") or item.get("assessment") or {}
        validation = item.get("validation") or {}
        role = (assessment.get("role_judgment") or {}).get("operational_role", "—")
        score = f"{validation.get('score')}%" if item.get("status") == "valid" else "—"
        lines.append(f"| {item['index']} | {str(record.get('name') or '').replace('|', '\\|')} | {record.get('industry') or '—'} | {role} | {score} | {item.get('status')} |")
    for item in items:
        record = item["record"]
        lines.extend(["", "---", "", f"# {item['index']}. {record.get('name')}", "", "### 输入记录", "", original_markdown(record), ""])
        if item.get("status") == "valid":
            lines.append(render_assessment(item.get("display_assessment") or item["assessment"], item["validation"]))
        else:
            lines.extend(["### Hermes 背调失败", "", "- " + "\n- ".join(item.get("errors") or ["未知错误"])])
    markdown_path = run_dir / "comparison.md"
    markdown_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    rows: list[str] = []
    cards: list[str] = []
    for item in items:
        record = item["record"]
        assessment = item.get("display_assessment") or item.get("assessment") or {}
        validation = item.get("validation") or {}
        role = (assessment.get("role_judgment") or {}).get("operational_role", "—")
        score = f"{validation.get('score')}%" if item.get("status") == "valid" else "—"
        rows.append(f"<tr><td>{item['index']}</td><td>{html.escape(str(record.get('name') or ''))}</td><td>{html.escape(str(role))}</td><td>{html.escape(score)}</td><td>{html.escape(str(item.get('status')))}</td></tr>")
        body = render_assessment_html(assessment, validation) if item.get("status") == "valid" else "<p>失败：" + html.escape("; ".join(item.get("errors") or [])) + "</p>"
        cards.append(f"<section><h2>{html.escape(str(record.get('name') or ''))}</h2><h3>输入记录</h3><pre>{html.escape(original_markdown(record))}</pre><h3>Hermes 背调</h3>{body}</section>")
    html_path = run_dir / "comparison.html"
    html_path.write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>输入记录与 Hermes 背调</title><style>body{font:15px/1.6 -apple-system,sans-serif;max-width:1400px;margin:24px auto;padding:0 20px;color:#172033}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #dbe3ec;text-align:left}th{background:#eef3f8}section{border-top:2px solid #dbe3ec;margin-top:30px;padding-top:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;padding:14px;border-radius:8px}</style>"
        f"<h1>输入记录与 Hermes 背调对照</h1><p>样本 {len(items)} 家；有效 {valid}；失败 {failed}。</p><table><thead><tr><th>#</th><th>公司</th><th>Hermes 角色</th><th>匹配度</th><th>状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table>{''.join(cards)}</html>",
        encoding="utf-8",
    )
    return markdown_path, html_path


def validate_selected_records(records: Any, source: Path | None = None) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"Selected companies file must contain a non-empty list: {source or 'input'}")
    seen: set[str] = set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise RuntimeError(f"Selected companies item {index} must be an object")
        if not isinstance(record.get("name"), str) or not record["name"].strip():
            raise RuntimeError(f"Selected companies item {index}.name must be a non-empty string")
        if "id" not in record:
            record["id"] = f"input-{index:03d}"
        elif not isinstance(record["id"], str) or not record["id"].strip():
            raise RuntimeError(f"Selected companies item {index}.id must be a non-empty string")
        record_id = record["id"].strip()
        if record_id in seen:
            raise RuntimeError(f"Selected companies has duplicate id: {record_id}")
        seen.add(record_id)
        if "website" in record:
            website = _normalise_url(record["website"])
            parsed = urlparse(website)
            if parsed.scheme not in {"http", "https"} or not hostname(website) or "." not in hostname(website):
                raise RuntimeError(f"Selected companies item {index}.website has no usable domain")
    return records


def _load_selected(path: Path) -> list[dict[str, Any]]:
    try:
        return validate_selected_records(json.loads(path.read_text(encoding="utf-8")), path)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Selected companies file is invalid: {path}: {exc}") from exc


def _run_id(source: str, count: int, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{source}-n{count:03d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run company research from a selected file or the optional read-only CRM sampler")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--selected-file", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--no-zero-review", action="store_true", help="Disable the one-time review of valid 0%% results")
    parser.add_argument("--reasoning", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--hermes", type=Path, default=DEFAULT_HERMES)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not 1 <= args.workers <= 6:
        parser.error("--workers must be between 1 and 6")
    if not 1 <= args.timeout <= 1800:
        parser.error("--timeout must be between 1 and 1800")
    if not 1 <= args.max_attempts <= 5:
        parser.error("--max-attempts must be between 1 and 5")
    load_env_file(args.env_file)
    for required in (resolved_validator(),):
        if not required.is_file():
            raise RuntimeError(f"Project validator is unavailable: {required}")
    if not args.hermes.is_file() or not os.access(args.hermes, os.X_OK):
        raise RuntimeError(f"Hermes executable is unavailable: {args.hermes}")

    if args.selected_file:
        selected_path = args.selected_file.resolve()
        records = _load_selected(selected_path)
        run_dir = args.output_root.resolve() / _run_id("file", len(records))
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "selected-companies.json").write_text(selected_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        records = read_candidates(args.limit)
        run_dir = args.output_root.resolve() / _run_id("crm", len(records))
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "selected-companies.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    jobs = list(enumerate(records, 1))
    items: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                research_one,
                record,
                index,
                run_dir,
                args.hermes,
                args.timeout,
                args.reasoning,
                max_attempts=args.max_attempts,
                review_zero_score=not args.no_zero_review,
            ): index
            for index, record in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            items.append(future.result())
    items.sort(key=lambda item: item["index"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        translations = [
            pool.submit(localize_item, item, args.hermes, args.timeout, args.reasoning)
            for item in items
            if item.get("status") == "valid"
        ]
        for future in concurrent.futures.as_completed(translations):
            future.result()
    write_reports(run_dir, items)
    valid = sum(item.get("status") == "valid" for item in items)
    durations = [float(item.get("duration_seconds") or 0) for item in items]
    summary = {
        "selected": len(items),
        "valid": valid,
        "failed": len(items) - valid,
        "average_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), **summary}, ensure_ascii=False))
    return 0 if valid == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
