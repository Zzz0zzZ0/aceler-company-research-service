# Aceler Company Research Trial

本项目的核心链路接收来源中立的公司身份线索，使用 AnySearch 提供最多 3 个可信页面，再由标准库 Orchestrator 编排 Evidence Agent、Catalog Router、Lead、条件式 Recall Critic 和按需 Arbiter，按 `aceler-company-research` 仓库契约输出一份结构化背调。公司名是唯一必填项；官网和 LinkedIn 可选，行业、评级、背景或联系人等 CRM 字段既不必提供，也不会因缺失而降低评分。Twenty CRM 只是一个可选的只读抽样入口。每份候选 JSON 均交给仓库 validator；最终状态只有 `valid` 或 `failed`。

另提供显式启用的 CRM 批量补充适配器，复用同一背调模块；首次使用 `--apply` 或 `apply` 命令启用写入，后台任务续跑保留此前的写入模式。该批次模式还按授权软删除有效背调且匹配度低于 20 分的公司，失败与主体不确定的记录不删除。支持固定清单、逐公司检查点、后台运行、停止和续跑，以及 AnySearch 额度耗尽暂停与本机通知，见 [批量补充操作说明](docs/crm-enrichment.md)。默认背调/API/抽样入口保持原有行为。

新机器或同事的 Codex 请不要只照本页的简版命令安装。完整的固定版本、Hermes profile、业务记忆、AnySearch、Codex Skill 自动发现和验收步骤见 [`INSTALL-CODEX.md`](INSTALL-CODEX.md)。

跨机器复现以基准机 `git rev-parse HEAD` 的完整提交号为准；`./scripts/verify-install.sh` 检查当前安装，`./scripts/verify-install.sh <基准提交号>` 额外核对提交及受跟踪文件是否干净。验收不再锁定历史 tag；profile 与 MEMORY 均对照当前仓库文件。

## Setup

先确认 `python3` 为 3.11 或以上，再创建本机虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
test -f config/local.env || cp config/local.env.example config/local.env
```

只有使用默认 CRM 抽样入口时，才需要在 `config/local.env` 中填写本机 CRM 连接配置。固定文件、Python API 或 JSON stdin/stdout 调用不需要 CRM。该文件和运行结果不会进入 Git。

### Hermes 精确运行配置

仓库直接提供当前生产使用的完整通用业务记忆和 Hermes profile 配置：[`config/hermes/aceler-memory/`](config/hermes/aceler-memory/)。它包含完整产品主档、工艺映射、客户画像、评分和证据边界，没有删减业务规则。当前基准运行环境为 Hermes Agent `0.20.4`、MiniMax-M3、`minimax-cn` provider；不同模型或版本不属于精确复现。

profile 的兼容默认模型仍为 MiniMax-M2.7，服务通过显式 `--model MiniMax-M3 --provider minimax-cn` 覆盖它。`ACELER_HERMES_MODEL` / `ACELER_HERMES_PROVIDER` 可临时覆盖服务配置；复现时须核对结果 `usage` 中的实际模型与 provider。

```bash
hermes profile create aceler-memory --no-skills \
  --description "Aceler approved product and industrial-process knowledge"
install -m 644 config/hermes/aceler-memory/config.yaml \
  "$HOME/.hermes/profiles/aceler-memory/config.yaml"
install -m 600 config/hermes/aceler-memory/MEMORY.md \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

在该 profile 自己的 `.env` 中配置调用方持有的 `MINIMAX_CN_API_KEY`，不要提交密钥。`hermes profile create` 默认生成 `aceler-memory` 包装命令，与本项目默认调用路径一致。已有同名 profile 时先比较配置，不要直接覆盖。跨机器对照还要求相同项目提交、输入、reasoning 和并发参数；排查检索时保留实时证据并记录缓存，仅做语义 A/B 时才复用同一份已保存证据。记忆不是网页来源，不能进入 `sources`。

## Run

```bash
.venv/bin/python -m company_research_trial.company_research_trial
```

默认报告写入 `outputs/company-research-trial/<UTC时间>-<来源>-n<公司数>/`，例如 `20260827T071500Z-crm-n020` 或 `20260827T071500Z-file-n005`。CRM 查询包含 `BEGIN READ ONLY`，不会写 CRM 或接入发信流程。固定样本可以这样运行：

```bash
.venv/bin/python -m company_research_trial.company_research_trial \
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
  | .venv/bin/python -m company_research_trial.research_api
```

stdout 始终只有一个 JSON 对象。退出码 `0` 表示 `valid`，`1` 表示背调完成但结果为 `failed`，`2` 表示输入或运行配置错误。请求只接受 `name`、`website`、`linkedin_url`；调用仍会在 `outputs/company-research-trial/<UTC时间>-api-n001/` 保留完整审计产物。

每家公司流程固定为：来源中立的 identity seed（可只有公司名）→ AnySearch 批量检索主体/产品与工厂/工艺并提取最多 3 页 → 长页面 Evidence Agent 引文核验与事实压缩 → Catalog Router 召回优先选取相关产品行 → Lead → 条件 Recall Critic → 按需 Arbiter → 仓库 validator。各角色只获得完成自己任务所需的上下文：Lead 不再接收整页原文和全部产品规则；Recall 独立使用完整产品矩阵审计 Router 漏选；Arbiter 只看争议产品规则和两份候选。原始证据仍保存在审计文件中，不用业务正则替代模型做语义判断。

普通请求仅在主检索抛出失败时调用一次已有的语义备用检索。主检索成功时直接返回原证据（包括缓存与只有公司名的输入），不因证据偏弱而扩展检索或改写证据。备用检索必须明确返回 `identity_status=confirmed` 且不存在重试后主体仍未解决的标记，才继续原评分流程；`related`、`ambiguous`、缺失身份状态或备用检索失败均继续返回失败。此身份门槛不代表产品/工艺缺口已关闭，也不代表最终跟进判断正确。显式 `refresh_evidence_cache=True` 仍保留原有刷新检索语义。

成功恢复时 `anysearch-meta.json` 的 `mode` 为 `failure_recovery`，`recall_recovery.primary_error` 保存脱敏的主检索错误，`retrieval_agent_calls` 单列检索角色调用数。`call_counts_scope=recovery_only` 表示其中的检索/提取计数仅覆盖备用检索：旧主检索异常不携带完整计数，不能将这些数字当作整条失败恢复链路的总成本。没有可信证据时，错误明确说明评分 Agent 未启动。

2026-09-08 的最小失败恢复版本通过 136 项回归、validator 自检与编译；100-3 历史证据路由回放中，原 98 家成功记录全部原样返回、不调用补检，2 条失败记录的备用证据中接受 1 条、拒绝主体不确定的 1 条。此回放没有重新评分，不能称为 99/100 全流程有效。真实第 88 家联网回测本次仅确认关联主体，仍拒绝；独立 Hatria 故障注入测试（只模拟主检索抛错，备用检索和评分均真实执行）得到 validator-valid 结果。记录在本地 `outputs/failure-only-recovery-20260908/`。本次只保留失败恢复，没有恢复此前已撤回的默认弱证据扩展，也不声称整体精确率或跨 Mac 有效率已提高。

输入字段只是待核验线索；公司角色、工艺和产品映射以本次证据包为准。AnySearch 证据包只采集一次，后续 Agent 禁止搜索。Lead 或校验失败时默认最多尝试 3 次，可用 `--max-attempts 1` 关闭重试。重试只修正 JSON、枚举和证据引用，不自动放行；每轮保留独立的 raw、usage、`evidence-bundle.json` 和 `orchestration.json` 审计文件。

### 当前验证基线

2026-09-04 在 100 家 CRM 标注集、MiniMax-M3、5 并发上的同证据语义 A/B 结果为：100/100 有效，召回率 91.07%，精确率 82.26%，TP/FP/TN/FN 为 51/11/33/5。对比旧版，召回率由 87.50% 提高 3.57 个百分点，精确率由 84.48% 下降 2.22 个百分点，准确率保持 84.00%。

2026-09-07 在新测试集 100-4、MiniMax-M3、5 并发的实时全流程结果为：100/100 有效，召回率 88.57%，精确率 80.52%，准确率 77.00%，TP/FP/TN/FN 为 62/15/15/8；人工正例/负例为 70/30。该批次同时通过召回率高于 80% 与精确率不低于 75% 的门槛，但负例特异度仅为 50.00%，下一轮应优先收紧上游供应商/同行、Holding/集团主体和设备工程邻接路线，同时保持召回门槛。正常 Lead 路径最大输入约 31,073 字符；AB Megamet 的 Evidence Agent 未产出合法 JSON，失败开放回退原证据后达到 40,309 字符，说明异常降级路径仍有进一步压缩空间。

同日 100-3 使用原流程、MiniMax-M3、5 并发运行，98/100 有效，召回率 83.93%、精确率 83.93%、准确率 81.00%；TP/FP/TN/FN 为 47/9/34/8，另有正例、负例各 1 家检索失败，未额外补跑。召回率按全部 56 家人工正例计算，准确率按全部 100 家计算。耗时 1,492.6 秒，Recall 触发 19 次、采用 0 次；本地审计目录为 `outputs/semantic-decision-validation/20260907T033244Z-testset100-3-m3/`（不进入 Git）。原七列 Markdown 只在兼容副本中补空地址列、展开网址链接，人工标签未改动。

100-3 有 5 家命中缓存，98 家有效记录中 92 家取得过本机 HTTP 抓取页面。因此整体有效率不能当作 AnySearch API 成功率；复制仓库后还须核对外部 AnySearch CLI、key 配置、Python/Node、macOS 系统代理和实际 `input-records.json`。详见安装文档的跨 Mac 检索排查；离线验收不代替联网验证。

2026-09-04 同证据语义 A/B 中，Lead 实际输入 token 中位数从 16,101 降至 4,974，最大值从 43,402 降至 6,572；所有语义 Agent 总输入 token 从 2,492,831 降至 917,868，减少 63.18%。Agent 调用由 139 次增至 225 次，但墙钟时间仅由 781.6 秒增至 806.1 秒，单家中位耗时由 33.2 秒降至 29.1 秒。该基线复用同一批已保存证据，因此 AnySearch 为 0 次；另外的 SARRALLE 实时冒烟已验证 Evidence Agent 能将 15,543 字符原页压缩为 15 条引文可核验事实和 4,565 字符下游上下文。

主 Hermes 调用必须直接用中文填写所有展示性自由文本，并保留公司/人名、产品专名、牌号、工艺缩写、数字和单位。Validator 完成后，系统剔除这些允许保留的英文专名；只有仍检测到英文说明时才执行一次失败开放的中文本地化。原始 canonical assessment、分数、枚举、证据 ID、URL 和产品字段保持不变；翻译结果单独写入 `display_assessment` 与 `localized-assessment.json`，仅供报告和看板使用。翻译超时、输出结构变化或受保护术语被改动时直接显示原文，不改变背调状态或主调用结果。

首次合法结果为 0%，或低于 55% 且已经确认相关工艺、材料角色、采购方向或渠道角色时，系统使用同一证据包调用独立 Recall Critic，专门排查生产投入、高温耗材和技术渠道是否被遗漏。Critic 改变分数、跟进结论或产品路线时必须再经 Arbiter；仲裁无效或拒绝时保留 Lead，且整个过程不会触发新搜索。兼容性关闭开关仍为 `--no-zero-review`。

Hermes prompt 使用 `$aceler-company-research` 与唯一 JSON skeleton。Hermes 基于完整证据做五维语义评分：`production_process_need`（0–30）、`catalog_fit`（0–30）、`consumption_intensity`（0–20）、`demand_recurrence`（0–10）、`company_role_fit`（0–10），validator 只验范围并求和后向下取 5。评分覆盖直接消耗、分销、工程/规格影响、互补供应和产品组合合作；已确认的公司产品/工艺可支持合理工业推断，未公开采购或私有配方只降低置信度，不把已成立的路径清零。行业标签或遥远邻接关系本身仍不加分。

产品名称必须来自固定 26 项目录。Graphite Electrode 需要确认 EAF；感应炉不使用石墨电极，镁质方向在没有衬里化学时只能写有依据的推测、低优先级并提出确认问题，不能标为已确认。不能为了填表发明没有官网依据的产品方向。

Validator 只硬校验 JSON 结构、合法枚举与范围、固定产品目录、证据 ID 和来源 URL 溯源。产品/工艺是否成立由 Hermes 依据完整证据包和 skill 契约判断；validator 不再对 `confirmed_processes` 自由文本做关键词或精确字符串裁决。置信度与身份/官方证据的矛盾只产生 warning，不触发重试或失败。

## Validator

```bash
.venv/bin/python skill/aceler-company-research/scripts/validate_assessment.py --self-test
```

服务运行只使用仓库内随提交固定的 Skill 契约和 validator，不依赖另一份 Hermes 全局 Skill。若同事还要在 Codex/Hermes 中直接调用独立 Skill，再单独安装同一提交中的 `skill/aceler-company-research/`。不要添加版本字段；历史结果仅由看板只读浏览，不迁移旧字段。

## Test

```bash
.venv/bin/python -m unittest \
  company_research_trial.test_company_research_trial \
  company_research_trial.test_dashboard \
  company_research_trial.test_research_api \
  company_research_trial.test_orchestration \
  company_research_trial.test_structured_evidence \
  company_research_trial.test_structured_evidence_pilot \
  company_research_trial.test_semantic_decision_validation
.venv/bin/python -m py_compile company_research_trial/company_research_trial.py company_research_trial/agent_contracts.py company_research_trial/orchestration.py company_research_trial/structured_evidence.py company_research_trial/dashboard.py company_research_trial/research_api.py scripts/semantic_decision_validation.py
```

## 本地看板：结果只读 + 单家公司背调

```bash
.venv/bin/python -m company_research_trial.dashboard
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
.venv/bin/python -m company_research_trial.dashboard --host 127.0.0.1 --port 8766
```

默认的 `0.0.0.0` 会向当前网络暴露看板；建议仅在可信局域网中使用。AnySearch Key 设置接口仍只允许本机回环请求。
