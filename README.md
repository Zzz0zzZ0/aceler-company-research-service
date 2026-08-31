# Aceler Company Research Trial

本项目的核心链路接收来源中立的公司身份线索，使用 AnySearch 提供 1–2 个可信页面，再让 Hermes 按 `aceler-company-research` 仓库契约输出一份结构化背调。公司名是唯一必填项；官网和 LinkedIn 可选，行业、评级、背景或联系人等 CRM 字段既不必提供，也不会因缺失而降低评分。Twenty CRM 只是一个可选的只读抽样入口。每份 Hermes JSON 原样交给仓库 validator；最终状态只有 `valid` 或 `failed`。

## Setup

```bash
python3 -m pip install -r requirements.txt
cp config/local.env.example config/local.env
```

只有使用默认 CRM 抽样入口时，才需要在 `config/local.env` 中填写本机 CRM 连接配置。固定文件、Python API 或 JSON stdin/stdout 调用不需要 CRM。该文件和运行结果不会进入 Git。

### Hermes profile 一致性

仓库提供一份脱敏的 [`hermes-memory-seed.md`](skill/aceler-company-research/references/hermes-memory-seed.md)，供团队新建独立 Hermes profile 时复制。它只包含稳定产品/工艺和判断边界，不包含公司事实、CRM 数据、会话或密钥，也不能作为背调来源。

```bash
hermes profile create aceler-memory --description "Aceler company research"
install -m 600 \
  skill/aceler-company-research/references/hermes-memory-seed.md \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

`hermes profile create` 默认会生成 `aceler-memory` 包装命令。已有同名 profile 时先比较现有 `MEMORY.md`，不要直接覆盖。模型、Hermes 版本、项目提交、证据包和 Skill 契约仍需分别保持一致；该记忆种子只用于减少规则漂移。

## Run

```bash
python3 -m company_research_trial.company_research_trial
```

默认报告写入 `outputs/company-research-trial/<UTC时间>-<来源>-n<公司数>/`，例如 `20260827T071500Z-crm-n020` 或 `20260827T071500Z-file-n005`。CRM 查询包含 `BEGIN READ ONLY`，不会写 CRM 或接入发信流程。固定样本可以这样运行：

```bash
python3 -m company_research_trial.company_research_trial \
  --selected-file outputs/company-research-trial/<old-run>/selected-companies.json \
  --workers 3
```

## 供其他模块调用

同一台机器上的 Python 模块可以直接调用当前生产背调链路，不读取 CRM：

```python
from company_research_trial.research_api import research_company

result = research_company(
    {
        "name": "Hatria",
        "website": "https://hatria.com",
        "linkedin_url": None,
    }
)
```

返回对象固定包含 `trace_id`、`status`、`assessment`、`validation`、`report_markdown`、`usage` 和 `errors`。`status` 只有 `valid` / `failed`；检索、Hermes 重试、零分复核、validator 和审计文件仍完全复用当前生产实现。

非 Python 调用方使用 JSON stdin/stdout 适配器：

```bash
printf '%s\n' '{"name":"Hatria","website":"https://hatria.com"}' \
  | python3 -m company_research_trial.research_api
```

stdout 始终只有一个 JSON 对象。退出码 `0` 表示 `valid`，`1` 表示背调完成但结果为 `failed`，`2` 表示输入或运行配置错误。请求只接受 `name`、`website`、`linkedin_url`；调用仍会在 `outputs/company-research-trial/<UTC时间>-api-n001/` 保留完整审计产物。

每家公司流程固定为：来源中立的 identity seed（可只有公司名）→ AnySearch 批量检索主体/产品与工厂/工艺并提取最多 2 页 → Hermes research → JSON parse → 仓库 validator。输入字段只是待核验线索；公司角色、工艺和产品映射以本次证据包为准。AnySearch 证据包只采集一次；Hermes 或校验失败时默认最多尝试 3 次，可用 `--max-attempts 1` 关闭重试。重试只修正 JSON、枚举和证据引用，不自动放行；每轮保留独立的 `hermes-raw-attempt-N.txt`、usage 和错误审计。

主 Hermes 调用必须直接用中文填写所有展示性自由文本，并保留公司/人名、产品专名、牌号、工艺缩写、数字和单位。Validator 完成后，系统剔除这些允许保留的英文专名；只有仍检测到英文说明时才执行一次失败开放的中文本地化。原始 canonical assessment、分数、枚举、证据 ID、URL 和产品字段保持不变；翻译结果单独写入 `display_assessment` 与 `localized-assessment.json`，仅供报告和看板使用。翻译超时、输出结构变化或受保护术语被改动时直接显示原文，不改变背调状态或主调用结果。

首次合法结果恰好为 0% 时，系统默认使用同一证据包和首次 JSON 做一次独立复核，专门排查生产投入、高温耗材和技术渠道是否被遗漏。复核可以维持 0%，不会触发新搜索，也不会重复复核；复核输出无效时保留首次合法结果。紧急回退可在运行命令中加入 `--no-zero-review`，完整记录见 [`ZERO-SCORE-REVIEW-ROLLBACK.md`](ZERO-SCORE-REVIEW-ROLLBACK.md)。

Hermes prompt 使用 `$aceler-company-research` 与唯一 JSON skeleton。评分完全采用产品/工艺主导的五维：`production_process_need`（0–30）、`catalog_fit`（0–30）、`consumption_intensity`（0–20）、`demand_recurrence`（0–10）、`company_role_fit`（0–10），总分向下取 5。采购可能性、供应商、认证、准入、地域和来源数量只记录在证据状态、置信度、研究状态、进入门槛或下一步问题中，不改变产品匹配分。

产品名称必须来自固定 26 项目录。Graphite Electrode 需要确认 EAF；感应炉不使用石墨电极，镁质方向在没有衬里化学时只能写有依据的推测、低优先级并提出确认问题，不能标为已确认。不能为了填表发明没有官网依据的产品方向。

Validator 只硬校验 JSON 结构、合法枚举与范围、固定产品目录、证据 ID 和来源 URL 溯源。产品/工艺是否成立由 Hermes 依据完整证据包和 skill 契约判断；validator 不再对 `confirmed_processes` 自由文本做关键词或精确字符串裁决。置信度与身份/官方证据的矛盾只产生 warning，不触发重试或失败。

## Validator

```bash
python3 skill/aceler-company-research/scripts/validate_assessment.py --self-test
```

项目 skill 与 Hermes 安装版应保持一致。安装后可在 Hermes 的 skill 目录运行同一条自检命令。不要添加版本字段；历史结果仅由看板只读浏览，不迁移旧字段。

## Test

```bash
python3 -m unittest company_research_trial.test_company_research_trial
python3 -m unittest company_research_trial.test_dashboard
python3 -m unittest company_research_trial.test_research_api
python3 -m py_compile company_research_trial/company_research_trial.py company_research_trial/dashboard.py company_research_trial/research_api.py
```

## 本地看板：结果只读 + 单家公司背调

```bash
python3 -m company_research_trial.dashboard
```

默认监听 `127.0.0.1:8765`。看板只读扫描本地 `result.json`，直接读取 validator 生成的 `score` 与 `level`。
看板采用左侧公司队列、右侧研究详情的并排审阅布局；结果区保持只读，“新建背调”抽屉可以提交一家公司。公司名必填，官网和 LinkedIn 可选，提交内容只包含 `name`、`website`、`linkedin_url` 三个字段，不读取或写入 CRM。一次只允许一个手工背调任务，完成后自动刷新并打开新的运行批次；CLI 返回失败状态但已生成合法结果时，失败结果仍可在看板查看。

需要让同一局域网中的设备访问时，显式监听全部网络接口：

```bash
python3 -m company_research_trial.dashboard --host 0.0.0.0 --port 8765
```

`0.0.0.0` 会暴露该端口；仅在可信网络和防火墙规则明确时使用。默认值仍保持为更安全的 `127.0.0.1`。
