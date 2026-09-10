#!/usr/bin/env bash

set -euo pipefail

ANYSEARCH_COMMIT="4d6cef918e9338c9deef43b81ac0f7e22606825f"
ANYSEARCH_SHA256="e4944fef758fae860d26b15460f5940f198841c2f965775ec9a2b36092e0edf9"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
ANYSEARCH_DIR="$HOME/.codex/skills/anysearch"
PROFILE_DIR="$HOME/.hermes/profiles/aceler-memory"

pass() {
  printf 'PASS  %s\n' "$1"
}

fail() {
  printf 'FAIL  %s\n' "$1" >&2
  exit 1
}

hash_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

cd "$ROOT_DIR"

[[ $# -le 1 ]] || fail "用法: scripts/verify-install.sh [基准提交号或 ref]"
head_commit="$(git rev-parse HEAD)"
if [[ $# -eq 1 ]]; then
  expected_commit="$(git rev-parse --verify --end-of-options "${1}^{commit}" 2>/dev/null || true)"
  [[ -n "$expected_commit" && "$head_commit" == "$expected_commit" ]] \
    || fail "仓库 HEAD 与指定基准不一致: $1 (当前 $head_commit)"
  git diff --quiet HEAD -- || fail "受跟踪文件存在未提交修改，无法确认与指定基准一致"
fi
pass "仓库提交: $head_commit"
PROFILE_SHA256="$(hash_file config/hermes/aceler-memory/config.yaml)"
MEMORY_SHA256="$(hash_file config/hermes/aceler-memory/MEMORY.md)"

[[ -f .agents/skills/aceler-company-research/SKILL.md ]] \
  || fail "Codex repo-scoped Skill 不可读"
pass "Codex repo-scoped Skill"

[[ -x "$PYTHON_BIN" ]] || fail "缺少 .venv；先按文档创建 Python 环境"
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "项目 Python 必须为 3.11+"
pass "项目 Python: $("$PYTHON_BIN" --version 2>&1)"
"$PYTHON_BIN" - <<'PY'
import os
from company_research_trial.company_research_trial import (
    DEFAULT_ENV_FILE, DEFAULT_HERMES_MODEL, DEFAULT_HERMES_PROVIDER, load_env_file,
)
load_env_file(DEFAULT_ENV_FILE)
model = os.getenv("ACELER_HERMES_MODEL", DEFAULT_HERMES_MODEL)
provider = os.getenv("ACELER_HERMES_PROVIDER", DEFAULT_HERMES_PROVIDER)
if (model, provider) != ("MiniMax-M3", "minimax-cn"):
    raise SystemExit("FAIL  服务模型/provider 与 M3/minimax-cn 基准不一致；检查 ACELER_HERMES_MODEL/PROVIDER")
print("PASS  服务实际调用配置: MiniMax-M3 / minimax-cn（显式覆盖 profile 默认模型）")
PY

command -v node >/dev/null 2>&1 || fail "缺少 Node.js"
pass "Node.js: $(node --version)"

command -v hermes >/dev/null 2>&1 || fail "PATH 中没有 hermes"
hermes_version="$(hermes --version 2>&1 | sed -n '1p')"
[[ "$hermes_version" == *"Hermes Agent v0.20.4"* ]] \
  || fail "Hermes 不是 0.20.4: $hermes_version"
pass "$hermes_version"

[[ -d "$ANYSEARCH_DIR/.git" ]] || fail "AnySearch 未安装到固定路径"
[[ "$(git -C "$ANYSEARCH_DIR" rev-parse HEAD)" == "$ANYSEARCH_COMMIT" ]] \
  || fail "AnySearch commit 不一致"
[[ "$(hash_file "$ANYSEARCH_DIR/scripts/anysearch_cli.js")" == "$ANYSEARCH_SHA256" ]] \
  || fail "AnySearch Node CLI 哈希不一致"
node "$ANYSEARCH_DIR/scripts/anysearch_cli.js" doc >/dev/null \
  || fail "AnySearch Node CLI 离线 doc 失败"
pass "AnySearch v3.1.0、commit 和 CLI 哈希"

[[ -f "$PROFILE_DIR/config.yaml" ]] || fail "缺少 aceler-memory config.yaml"
[[ -f "$PROFILE_DIR/memories/MEMORY.md" ]] || fail "缺少完整 MEMORY.md"
[[ "$(hash_file "$PROFILE_DIR/config.yaml")" == "$PROFILE_SHA256" ]] \
  || fail "aceler-memory config.yaml 哈希不一致"
[[ "$(hash_file "$PROFILE_DIR/memories/MEMORY.md")" == "$MEMORY_SHA256" ]] \
  || fail "aceler-memory MEMORY.md 哈希不一致"
[[ -x "$HOME/.local/bin/aceler-memory" ]] || fail "缺少 aceler-memory 包装命令"
[[ -f "$PROFILE_DIR/.env" ]] || fail "缺少 aceler-memory profile .env"
grep -Eq '^MINIMAX_CN_API_KEY=.+$' "$PROFILE_DIR/.env" \
  || fail "profile .env 缺少非空 MINIMAX_CN_API_KEY"
pass "Hermes profile、完整 MEMORY、包装命令和密钥变量"

"$PYTHON_BIN" -c 'import psycopg' || fail "requirements.txt 未完整安装"
pass "Python requirements"

"$PYTHON_BIN" skill/aceler-company-research/scripts/validate_assessment.py --self-test
"$PYTHON_BIN" -m unittest \
  company_research_trial.test_company_research_trial \
  company_research_trial.test_dashboard \
  company_research_trial.test_research_api \
  company_research_trial.test_orchestration \
  company_research_trial.test_structured_evidence \
  company_research_trial.test_structured_evidence_pilot \
  company_research_trial.test_semantic_decision_validation \
  company_research_trial.test_crm_enrichment \
  company_research_trial.test_retrieval_policy
"$PYTHON_BIN" -m py_compile \
  company_research_trial/company_research_trial.py \
  company_research_trial/agent_contracts.py \
  company_research_trial/orchestration.py \
  company_research_trial/structured_evidence.py \
  company_research_trial/dashboard.py \
  company_research_trial/research_api.py \
  scripts/semantic_decision_validation.py \
  scripts/crm_enrichment.py \
  company_research_trial/retrieval_policy.py \
  scripts/website_first_validation.py
pass "validator、单元测试和 Python 编译"

printf '\n离线安装验收通过；本脚本未调用 AnySearch、MiniMax 或 CRM。\n'
