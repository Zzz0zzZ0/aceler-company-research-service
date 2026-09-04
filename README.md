# Aceler Company Research Trial

本项目的核心链路接收来源中立的公司身份线索，使用 AnySearch 提供最多 3 个可信页面，再由标准库 Orchestrator 编排 Hermes Lead、条件式 Recall Critic 和按需 Arbiter，按 `aceler-company-research` 仓库契约输出一份结构化背调。公司名是唯一必填项；官网和 LinkedIn 可选，行业、评级、背景或联系人等 CRM 字段既不必提供，也不会因缺失而降低评分。Twenty CRM 只是一个可选的只读抽样入口。每份候选 JSON 均交给仓库 validator；最终状态只有 `valid` 或 `failed`。

新机器或同事的 Codex 请不要只照本页的简版命令安装。完整的固定版本、Hermes profile、业务记忆、AnySearch、Codex Skill 自动发现和验收步骤见 [`INSTALL-CODEX.md`](INSTALL-CODEX.md)。

## Setup

```bash
python3 -m pip install -r requirements.txt
cp config/local.env.example config/local.env
```

只有使用默认 CRM 抽样入口时，才需要在 `config/local.env` 中填写本机 CRM 连接配置。固定文件、Python API 或 JSON stdin/stdout 调用不需要 CRM。该文件和运行结果不会进入 Git。

### Hermes 精确运行配置

仓库直接提供当前生产使用的完整通用业务记忆和 Hermes profile 配置：[`config/hermes/aceler-memory/`](config/hermes/aceler-memory/)。它包含完整产品主档、工艺映射、客户画像、评分和证据边界，没有删减业务规则。当前基准运行环境为 Hermes Agent `0.20.4`、MiniMax-M3、`minimax-cn` provider；不同模型或版本不属于精确复现。

```bash
hermes profile create aceler-memory --no-skills \
  --description "Aceler approved product and industrial-process knowledge"
install -m 644 config/hermes/aceler-memory/config.yaml \
  "$HOME/.hermes/profiles/aceler-memory/config.yaml"
install -m 600 config/hermes/aceler-memory/MEMORY.md \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

在该 profile 自己的 `.env` 中配置调用方持有的 `MINIMAX_CN_API_KEY`，不要提交密钥。`hermes profile create` 默认生成 `aceler-memory` 包装命令，与本项目默认调用路径一致。已有同名 profile 时先比较配置，不要直接覆盖。精确复现还要求使用相同项目提交、输入、冻结证据包、reasoning 和并发参数；记忆不是网页来源，不能进入 `sources`。

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

返回对象固定包含 `trace_id`、`status`、`assessment`、`validation`、`report_markdown`、`usage` 和 `errors`。`status` 只有 `valid` / `failed`；检索、Lead 重试、条件 Recall、按需仲裁、validator 和审计文件均复用同一生产实现。

非 Python 调用方使用 JSON stdin/stdout 适配器：

```bash
printf '%s\n' '{"name":"Hatria","website":"https://hatria.com"}' \
  | python3 -m company_research_trial.research_api
```

stdout 始终只有一个 JSON 对象。退出码 `0` 表示 `valid`，`1` 表示背调完成但结果为 `failed`，`2` 表示输入或运行配置错误。请求只接受 `name`、`website`、`linkedin_url`；调用仍会在 `outputs/company-research-trial/<UTC时间>-api-n001/` 保留完整审计产物。

每家公司流程固定为：来源中立的 identity seed（可只有公司名）→ AnySearch 批量检索主体/产品与工厂/工艺并提取最多 3 页 → 不可变 `EvidenceBundle` → Lead → 条件 Recall Critic → 按需 Arbiter → 仓库 validator。输入字段只是待核验线索；公司角色、工艺和产品映射以本次证据包为准。AnySearch 证据包只采集一次，Recall 和 Arbiter 禁止搜索。Lead 或校验失败时默认最多尝试 3 次，可用 `--max-attempts 1` 关闭重试。重试只修正 JSON、枚举和证据引用，不自动放行；每轮保留独立的 raw、usage、`evidence-bundle.json` 和 `orchestration.json` 审计文件。

主 Hermes 调用必须直接用中文填写所有展示性自由文本，并保留公司/人名、产品专名、牌号、工艺缩写、数字和单位。Validator 完成后，系统剔除这些允许保留的英文专名；只有仍检测到英文说明时才执行一次失败开放的中文本地化。原始 canonical assessment、分数、枚举、证据 ID、URL 和产品字段保持不变；翻译结果单独写入 `display_assessment` 与 `localized-assessment.json`，仅供报告和看板使用。翻译超时、输出结构变化或受保护术语被改动时直接显示原文，不改变背调状态或主调用结果。

首次合法结果为 0%，或低于 55% 且已经确认相关工艺、材料角色、采购方向或渠道角色时，系统使用同一证据包调用独立 Recall Critic，专门排查生产投入、高温耗材和技术渠道是否被遗漏。Critic 改变分数、跟进结论或产品路线时必须再经 Arbiter；仲裁无效或拒绝时保留 Lead，且整个过程不会触发新搜索。兼容性关闭开关仍为 `--no-zero-review`。

Hermes prompt 使用 `$aceler-company-research` 与唯一 JSON skeleton。Hermes 基于完整证据做五维语义评分：`production_process_need`（0–30）、`catalog_fit`（0–30）、`consumption_intensity`（0–20）、`demand_recurrence`（0–10）、`company_role_fit`（0–10），validator 只验范围并求和后向下取 5。评分覆盖直接消耗、分销、工程/规格影响、互补供应和产品组合合作；已确认的公司产品/工艺可支持合理工业推断，未公开采购或私有配方只降低置信度，不把已成立的路径清零。行业标签或遥远邻接关系本身仍不加分。

产品名称必须来自固定 26 项目录。Graphite Electrode 需要确认 EAF；感应炉不使用石墨电极，镁质方向在没有衬里化学时只能写有依据的推测、低优先级并提出确认问题，不能标为已确认。不能为了填表发明没有官网依据的产品方向。

Validator 只硬校验 JSON 结构、合法枚举与范围、固定产品目录、证据 ID 和来源 URL 溯源。产品/工艺是否成立由 Hermes 依据完整证据包和 skill 契约判断；validator 不再对 `confirmed_processes` 自由文本做关键词或精确字符串裁决。置信度与身份/官方证据的矛盾只产生 warning，不触发重试或失败。

## Validator

```bash
python3 skill/aceler-company-research/scripts/validate_assessment.py --self-test
```

服务运行只使用仓库内随提交固定的 Skill 契约和 validator，不依赖另一份 Hermes 全局 Skill。若同事还要在 Codex/Hermes 中直接调用独立 Skill，再单独安装同一提交中的 `skill/aceler-company-research/`。不要添加版本字段；历史结果仅由看板只读浏览，不迁移旧字段。

## Test

```bash
python3 -m unittest company_research_trial.test_company_research_trial
python3 -m unittest company_research_trial.test_dashboard
python3 -m unittest company_research_trial.test_research_api
python3 -m unittest company_research_trial.test_orchestration
python3 -m py_compile company_research_trial/company_research_trial.py company_research_trial/agent_contracts.py company_research_trial/orchestration.py company_research_trial/dashboard.py company_research_trial/research_api.py
```

## 本地看板：结果只读 + 单家公司背调

```bash
python3 -m company_research_trial.dashboard
```

默认监听 `0.0.0.0:8766`，可以通过启动时显示的当前局域网 IP 和端口访问。看板只读扫描本地 `result.json`，直接读取 validator 生成的 `score` 与 `level`。
看板采用左侧公司队列、右侧研究详情的并排审阅布局；结果区保持只读，“新建背调”抽屉可以提交一家公司。公司名必填，官网和 LinkedIn 可选，提交内容只包含 `name`、`website`、`linkedin_url` 三个字段，不读取或写入 CRM。一次只允许一个手工背调任务，完成后自动刷新并打开新的运行批次；CLI 返回失败状态但已生成合法结果时，失败结果仍可在看板查看。

AnySearch key 可通过仅限本机的设置接口更换；接口只返回尾 4 位掩码，完整 key 不会出现在响应中：

```bash
curl http://127.0.0.1:8766/api/settings/anysearch
curl -X POST http://127.0.0.1:8766/api/settings/anysearch \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"替换为新的-key"}'
```

更新会原子写入 `config/local.env` 并刷新看板进程环境；之后新启动的背调任务使用新 key，已在运行的独立批次不会被中途切换。

只需要限制为本机访问时，显式监听回环接口：

```bash
python3 -m company_research_trial.dashboard --host 127.0.0.1 --port 8766
```

默认的 `0.0.0.0` 会向当前网络暴露看板；建议仅在可信局域网中使用。AnySearch Key 设置接口仍只允许本机回环请求。
