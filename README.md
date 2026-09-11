# Aceler 公司背调服务

面向 Aceler 产品组合的企业背调模块：核验公司主体，收集公开证据，识别公司角色、工艺和采购方向，输出可追溯的匹配评分、产品建议与报告。核心背调可脱离 CRM 运行；Twenty CRM 抽样和批量回填是可选适配器。

**交接分支：`codex/crm-enrichment-20260909`。** 本次交接包含 CRM 无效标记、联系人保护和 AnySearch Key 池；不要只克隆较早的 `main` 后假定包含这些功能。交接双方用 `git rev-parse HEAD` 记录完整提交号，复现时以同一提交为准。

**Git 只交付代码、测试和文档。当前队列、业务结果、恢复快照、Key 池及密钥配置均留在原机，不随本次推送迁移。** 新机器不能仅凭仓库恢复原机进度；也不要在另一台机器另建相同范围的写入队列与原机同时运行。

## 目录

- [功能边界与入口](#功能边界与入口)
- [安装与配置](#安装与配置)
- [如何启动](#如何启动)
- [CRM 数据规则](#crm-数据规则)
- [AnySearch Key 池](#anysearch-key-池)
- [作为另一项目的模块](#作为另一项目的模块)
- [日常维护](#日常维护)
- [更新、回退与迁移](#更新回退与迁移)
- [故障处理](#故障处理)
- [验收与指标](#验收与指标)
- [代码和文档导航](#代码和文档导航)

## 功能边界与入口

| 入口 | 用途 | CRM 访问 | 运行方式 |
| --- | --- | --- | --- |
| `research_api.research_company()` | Python 单家公司背调 | 无 | 同步函数调用 |
| `python -m company_research_trial.research_api` | JSON stdin/stdout，供其他语言调用 | 无 | 单次进程 |
| `python -m company_research_trial.company_research_trial --selected-file …` | 固定 JSON 公司清单 | 无 | 前台批量运行 |
| 同一批量 CLI，不传 `--selected-file` | 抽样背景薄弱的 CRM 公司 | 只读，默认最多 20 家 | 前台批量运行 |
| `python -m company_research_trial.dashboard` | 浏览结果、提交手工单家公司背调 | 无 | 前台 HTTP 服务 |
| `scripts/crm-enrichment` | 冻结清单、背调、受保护回填、暂停续跑 | 显式 `--apply` / `apply` 后可写公司 | 持久化后台队列 |
| `scripts/crm-enrichment key-ui` | 管理 Key 池及 CRM 队列 | 启动的 worker 按保存的写入模式执行 | 独立本机 HTTP 服务 |

公司名称是唯一必填线索；官网和 LinkedIn 可选。API 请求只接受 `name`、`website`、`linkedin_url`，网址须为有效 HTTP(S) URL。格式校验不等于公司主体已确认，主体仍需通过公开证据核验。缺失 CRM 背景、行业、评级或联系人不会降低核心背调评分。

核心背调状态只有 `valid` / `failed`；CRM 队列另有写入、复核、冲突和额度暂停等状态。`valid` 表示结果通过结构校验，不能直接解释为公司判断准确。本项目不发送开发信，不执行联系人跟进；其他系统的无效公司拦截需单独应用。

## 安装与配置

### 1. 获取正确版本

```bash
git clone --branch codex/crm-enrichment-20260909 \
  https://github.com/Zzz0zzZ0/aceler-company-research-service.git
cd aceler-company-research-service
git rev-parse HEAD
git status --short
```

以下命令默认在本仓库根目录执行。路径含空格或中文时，使用双引号包围变量。完整外部依赖安装步骤在 [INSTALL-CODEX.md](INSTALL-CODEX.md)，首次安装不能只执行 pip 后跳过它。

### 2. 安装依赖

| 依赖 | 本项目基准 | 作用 |
| --- | --- | --- |
| Python | 3.11+，使用项目 `.venv` | 主流程、看板、CRM 适配器 |
| Node.js | 基准 Node 22 | 调用 AnySearch CLI |
| Hermes Agent | `0.20.4` | 模型调用；不要无计划升级 |
| 模型 / provider | `MiniMax-M3` / `minimax-cn` | 以结果实际 `usage` 为准 |
| AnySearch | v3.1.0，固定提交 `4d6cef918e9338c9deef43b81ac0f7e22606825f` | 搜索与页面提取 |
| `psycopg[binary]` | 见 `requirements.txt` | CRM 数据库访问；无 CRM 时不连接 |

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
test -f config/local.env || cp config/local.env.example config/local.env
chmod 600 config/local.env
```

AnySearch 安装位置固定为 `~/.codex/skills/anysearch/scripts/anysearch_cli.js`；Hermes 默认执行文件为 `~/.local/bin/aceler-memory`。两者不包含在 Git 克隆中。完整 profile 配置和业务记忆在 `config/hermes/aceler-memory/`，按安装文档安装到本机 Hermes profile，不能删减业务记忆来加速。

profile 的兼容默认模型仍为 MiniMax-M2.7，服务显式覆盖为 M3 / minimax-cn；不要仅据 profile 判断实际模型。`ACELER_HERMES_MODEL` / `ACELER_HERMES_PROVIDER` 可覆盖运行配置，交接复现时应维持基准。

### 3. 配置的归属和优先级

| 配置 | 位置 / 变量 | 注意事项 |
| --- | --- | --- |
| MiniMax 凭据 | `~/.hermes/profiles/aceler-memory/.env` 中的 `MINIMAX_CN_API_KEY` | profile 私有文件设为 0600，不放入 CRM、邮箱等无关凭据 |
| 单 AnySearch Key | `config/local.env` 的 `ANYSEARCH_API_KEY` | 核心入口一般保留已有父进程环境值；CRM 入口优先读取本地文件中的 Key |
| 多 Key 池 | `config/anysearch-keys.json` | 用本机 Key 页面管理，0600，不手工打印内容 |
| 独立入口使用 Key 池 | `ANYSEARCH_KEY_POOL_FILE` 为池文件绝对路径 | CRM worker 自动接入；普通 CLI/API 需要显式设置 |
| CRM 连接 | `TWENTY_DB_HOST/PORT/NAME/USER/PASSWORD/SSLMODE/CONNECT_TIMEOUT`、`TWENTY_WORKSPACE_SCHEMA` | 可放独立 env 文件，用 `--crm-env` 指定；示例连接值不能直接用于生产 |
| 模型覆盖 | `ACELER_HERMES_MODEL`、`ACELER_HERMES_PROVIDER` | 每次对照实际 usage；环境中残留的旧值可能覆盖文件 |

普通 env 加载使用“已有环境变量优先”，不要把宿主项目的一整套环境误传入模块。CRM 先加载项目 env 再加载指定 CRM env，已存在的 CRM 变量不会被后者覆盖；应只在一个明确位置维护有效 CRM 配置。目标指纹不一致时队列拒绝执行，不要修改指纹绕过保护。

Key 设置页只返回脱敏标识，完整凭据不应出现在聊天、截图、命令行参数、提交或日志中。`config/local.env`、池文件及其临时文件均在 `.gitignore` 中。

### 4. 先做离线验收

```bash
bash scripts/verify-install.sh
```

它检查运行时版本、AnySearch 提交和 CLI 哈希、Hermes profile/业务记忆、validator、自测与编译，不调用付费搜索、模型或 CRM。对照交接提交且工作区干净时：

```bash
ACELER_REPRO_REF='交接提供的完整提交号'
bash scripts/verify-install.sh "$ACELER_REPRO_REF"
```

## 如何启动

### 无 CRM：单家公司冒烟与模块 API

以下会产生真实搜索及模型调用费用。离线验收通过后，先用一家公司验证，再扩大范围：

```bash
printf '%s\n' '{"name":"Hatria","website":"https://hatria.com"}' \
  | .venv/bin/python -m company_research_trial.research_api
```

stdout 为一个 JSON 对象，包含 `trace_id`、`status`、`assessment`、`validation`、`report_markdown`、`usage`、`errors`。退出码：`0` 有效结果，`1` 背调结果失败，`2` 输入或运行配置错误。错误对象的占位分数不能作为低相关度判断。

```python
from company_research_trial.research_api import research_company

result = research_company(
    {"name": "Hatria", "website": "https://hatria.com"},
    timeout=300,
    reasoning="medium",
    max_attempts=3,
)
```

`timeout` 是调用配置，不是整家公司总耗时上限；一家公司可能包含多轮检索、Agent、重试和翻译。

### 无 CRM：固定公司清单

创建本机 JSON 数组，例如 `inputs/companies.json`：

```json
[{"id":"sample-001","name":"Hatria","website":"https://hatria.com"}]
```

```bash
.venv/bin/python -m company_research_trial.company_research_trial \
  --selected-file inputs/companies.json --workers 3
```

`--selected-file` 读取的是 JSON，不是原始 Markdown 测试集。默认输出到 `outputs/company-research-trial/<UTC时间>-file-n…/`。不传该参数会走 CRM 只读抽样，不能将无参数命令当作“启动空服务”。

### 结果看板

```bash
mkdir -p outputs/company-research-trial
.venv/bin/python -m company_research_trial.dashboard \
  --host 127.0.0.1 --port 8766
```

打开 `http://127.0.0.1:8766/`。结果只读，新建背调一次接受一家，不写 CRM。上面是前台服务，终端 Ctrl+C 可停止；不会停止独立 CRM worker。

默认不传 `--host` 时监听 `0.0.0.0:8766`，会向当前网络暴露业务结果，交接默认使用回环地址。看板默认只扫描 `outputs/company-research-trial`。要浏览 CRM 批次结果，另选空闲端口并指定批次的父目录：

```bash
mkdir -p outputs/crm-enrichment
.venv/bin/python -m company_research_trial.dashboard \
  --host 127.0.0.1 --port 8767 --output-root outputs/crm-enrichment
```

看板单 Key 设置写入 `config/local.env`；CRM Key 池是另一份配置，开启池后不要仅修改单 Key 设置就假定 CRM 池已更新。池管理入口见下一节。

### CRM：新建批次

只有确需 CRM 补充时才操作。数据库账号需要读取公司、联系人、字段元数据；启用写入时还需公司字段更新权限，不能直接使用示例只读账号回填。

```bash
scripts/crm-enrichment snapshot \
  --run-dir outputs/crm-enrichment/my-batch \
  --crm-env /absolute/path/to/crm.env

scripts/crm-enrichment start \
  --run-dir outputs/crm-enrichment/my-batch \
  --workers 2 --limit 5 --dry-run

scripts/crm-enrichment status --run-dir outputs/crm-enrichment/my-batch
```

快照已有时不会重新覆盖。先看小批次的 `result.json`、`proposal.json` 和证据，待 worker 退出后再启用同一批次写入。确认要执行全量时：

```bash
scripts/crm-enrichment start \
  --run-dir outputs/crm-enrichment/my-batch \
  --workers 5 --limit 0 --apply
```

`--dry-run` 仍会消耗搜索和模型额度，只是不写 CRM。`apply` 子命令只处理已有提案/结果；`start --apply` 会继续背调并写入。CRM 并发范围 1–5，`--limit 0` 表示整个冻结清单。

### CRM：接管已有批次

先查状态。默认批次由本机 `outputs/crm-enrichment/latest.json` 指定；同时管理多个批次时，每条命令都应显式传 `--run-dir`。

```bash
scripts/crm-enrichment status
scripts/crm-enrichment stop
scripts/crm-enrichment status
# 确认 running=false 后，按需要续跑
scripts/crm-enrichment resume
```

`stop` 停止派发，等待在途公司完成后退出；`stopping` 不等于已停。`resume` 沿用保存的并发、范围和写入模式：此前 `--apply` 的批次续跑仍然写 CRM；此前 `--limit 5` 的批次不会自动变成全量。

worker 是脱离终端的后台进程，有文件锁避免同一批次重复启动。macOS 使用 `caffeinate` 防止运行期间自动空闲睡眠；关机、合盖和断电仍会中断。项目没有开机自启。不同批次和不同机器之间没有全局锁，不能并行执行覆盖相同公司的写入队列。

## CRM 数据规则

| 条件 / 字段 | 当前处理规则 |
| --- | --- |
| 筛选范围 | 公司未删除、`source=ISALES`、公司不是 `WU_XIAO`；无未删除联系人，或所有未删除联系人均为 `NO_REPLY` / `NEW` |
| 行业 `industry` | 仅补空值，只能使用 CRM 允许枚举；证据不足不硬填“其他” |
| 星级 `rating` | 仅补空值；0–19→1 星，20–39→2 星，40–59→3 星，60–79→4 星，80–100→5 星 |
| 背景 `background` | 保留原文；有实质新增或更正时追加带日期和来源的中文补充，空值直接填写 |
| 有效背调低于 20 分 | `status=valid`、validator 通过、主体确认且分数 `<20`，将公司 `level` 标为 `WU_XIAO`；低分分支优先于字段回填 |
| 失败 / 主体未确认 / 正好 20 分 | 不按低分标无效 |
| 公司已为一/二级 | 不自动降级，记录冲突 |
| 联系人一/二级 | `CUSTOMER`、`INQUIRY`、`QUALIFIED`、`NO_DEMAND` 转复核；其他非三级/空生命周期也不符合自动范围 |
| 联系人生命周期 | 不连带修改；低公司匹配度不等于联系人失效 |
| 写入保护 | 派发前重查范围，写前锁公司行并检查身份、字段、生命周期，UPDATE 再次核对范围 |

**当前策略不删除公司或联系人。** `deletion*.json` 只保留历史审计，不可作为继续删除的指令。旧版确曾执行公司软删除，数据库其他流程可能随后物理清理；恢复不能仅凭软删除回执推断原行或关联仍存在。恢复需要完整备份、当前关联和合并回执共同核对，不能盲目重建已合并公司或覆盖后来转移的联系人。

只读核查整个冻结清单（含已完成公司）：

```bash
scripts/crm-enrichment policy-review
```

它生成 `contact-policy-review.json`，列出无效公司和有二级及以上联系人的公司，统计联系人数量，不导出联系人姓名/邮箱。不会启动队列或写 CRM。详细字段保护、检查点及状态解释见 [CRM 操作说明](docs/crm-enrichment.md)。

## AnySearch Key 池

```bash
scripts/crm-enrichment key-ui --port 54101
```

打开命令输出的网址。本机可用端口为 54101 时入口是 `http://127.0.0.1:54101/`；不指定端口则自动选择，实际值记录在批次 `key-ui.json`。首次使用需要已有批次及 CRM 配置。命令本身是前台页面服务；已有页面进程时返回其地址，不再开第二个。

需要让页面脱离终端运行时：

```bash
mkdir -p outputs/service-logs
nohup scripts/crm-enrichment key-ui --port 54101 \
  > outputs/service-logs/key-ui.log 2>&1 < /dev/null &
```

- 最多 20 个 Key。“保存备用 Key”只保存；“保存并续跑”会按批次保存的写入模式启动。页面每 5 秒刷新，操作后立即刷新。
- 当前 Key 明确额度耗尽后自动切换下一个可用 Key；全部耗尽才保存 STOP、暂停并通知。普通 429、超时、无结果或认证失败不会触发额度切换。
- 首次启用池前要暂停 worker；池已启用时可以运行中追加 Key。充值后的 Key 需暂停后“恢复可用”，重复添加不会自动解除耗尽，也不猜测每日重置时间。
- 池状态使用进程间文件锁、原子写入和 0600 权限。旧在途请求只影响其实际使用的 Key，不会误标新 Key。重新启动页面/worker 后保留状态。
- 切换重试整个 CLI 命令；批次里已成功的查询可能重复请求。统计包含重试，不能用 CLI 次数或查询次数当作账单扣点。
- 这是本项目内的请求切换层，不是通用 HTTP 代理，不自动注册或获取新 Key。只读查看脱敏状态可用 `scripts/crm-enrichment status` 或页面 `/status`，不要打印池文件。

普通 CLI/API 显式接入同一池：

```bash
export ANYSEARCH_KEY_POOL_FILE="$PWD/config/anysearch-keys.json"
```

不设置时普通入口沿用原单 Key 行为；CRM worker 在池文件存在时自动设置。关闭页面不会停止 worker，页面显示的 Key“可用”是本地状态，不是远端余额实时查询。

## 作为另一项目的模块

保留完整目录，例如 `host-project/modules/company-research/`，不要只拷贝一个 Python 文件。必须包含 `company_research_trial/`、`skill/`、`config/hermes/`、依赖文件和脚本；`.agents/skills/aceler-company-research` 是仓库内相对符号链接，不要复制成指向旧机器的绝对链接。

推荐从宿主用本模块自己的解释器和工作目录调用 JSON 接口，避免同名包冲突及宿主环境覆盖：

```python
import json
import subprocess
from pathlib import Path

module_dir = Path("/absolute/path/host-project/modules/company-research")
completed = subprocess.run(
    [str(module_dir / ".venv/bin/python"),
     "-m", "company_research_trial.research_api",
     "--env-file", str(module_dir / "config/local.env")],
    input=json.dumps({"name": "Hatria", "website": "https://hatria.com"}),
    text=True, capture_output=True, cwd=module_dir, check=False,
)
if completed.returncode not in (0, 1, 2):
    raise RuntimeError("背调子进程异常退出，请检查本机 stderr")
result = json.loads(completed.stdout)
```

这是同步调用，宿主应提供足够长的总超时或放入自己的后台任务。示例默认继承宿主环境；集成前检查模型、代理和 Key 池环境变量，只传递确定需要的配置，不向网页或用户回传原始 stderr。Python 直接 import 也可，但需由宿主保证包可发现、Python 版本及依赖一致；本仓库没有提供可直接 `pip install -e .` 的打包配置。

模块可独立背调，不需要启动 Twenty Hermes、联系人检索或 CRM 发信系统。使用 CRM 队列时才配置真实数据库与批次路径。

## 日常维护

### 每次开始或接管时

1. `git status --short`、`git rev-parse HEAD`：确认版本及是否存在未提交改动。
2. `scripts/crm-enrichment status`：同时看 `running/state`、`progress.updated_at`、`in_flight` 和暂停原因。PID 文件可能留有已结束进程，不能只看 PID 数字。
3. 看 Key 页是否有可用 Key；单个 Key 耗尽并切换是正常事件，全部耗尽才需要补充额度。
4. 核对当前批次 `settings.json` 的 workers、limit、apply。该文件含本机路径，不需要对外发送。

### 运行期间与结束后

| 检查项 | 看什么 | 如何处理 |
| --- | --- | --- |
| 进度 | `progress.json`、`worker.log`、在途公司审计更新时间 | 长任务未结束不等于卡死；结合进程和日志判断 |
| 实际模型 | 新结果的 `usage.model/provider` 和 Agent usage | 保持 M3 / minimax-cn，漂移先暂停并定位配置 |
| 低分处理 | `invalidation.json` 对应的 result、score、身份及写前范围 | 不符合新策略则停止派发，保留证据 |
| 失败集中 | `error.json`、`proposal.json` 的 reason、原始模型/检索日志 | 技术故障和主体未确认分开处理，不人工改 valid |
| 花费趋势 | `request-usage.json` 的 search/extract/CLI attempts | 含失败及切换重试；缺少早期计量的历史不能补算账单 |
| 数据保护 | `apply.json`、写前字段、联系人范围 | 冲突跳过，不强制覆盖人工修改 |
| 完成 | `complete` 及分项计数 | 表示本轮尝试结束，不表示每家补充成功 |

`completed` 包含复核、冲突、失败和额度中断，不能当作实际写入数量。续跑会重新尝试技术失败，完成计数可能暂时降低。待复核结果通常保留检查点，不能把它们当技术失败循环重跑。

本机 Codex 定时监控是仓库外配置，**不会随 Git 克隆迁移**。交接后如需监控，应另行配置周期与通知条件；正常推进保持安静，新异常、全部额度耗尽或批次完成才通知，用户暂停时不擅自续跑。监控不应为巡检增加付费背调。

### 本地文件与保留原则

| 路径 | 内容 | 是否随 Git 交付 |
| --- | --- | --- |
| `outputs/company-research-trial/` | 独立背调输入、结果、报告、模型和证据审计 | 否 |
| `outputs/crm-enrichment/` | 当前/历史批次清单、进度、回执、恢复快照 | 否；本次当前队列不迁移 |
| `outputs/anysearch-cache/` | 七天证据缓存 | 否；跨机器默认不会命中同一缓存 |
| `config/local.env` | 本机服务配置及凭据 | 否 |
| `config/anysearch-keys.json` | Key 池、耗尽状态与尝试计数 | 否 |
| `~/.hermes/profiles/aceler-memory/` | 已安装 profile、完整业务记忆与密钥 | 否；外部运行依赖 |

保留完整批次的 `snapshot.json`、`manifest.json`、`settings.json`、`records/` 和写入审计。只备份 `result.json` 不足以恢复队列；字段回填快照也不等于完整 CRM 数据库备份。定期检查磁盘空间，在确认保留范围和完成独立备份前不要清理原始证据、删除回执或恢复资料。

## 更新、回退与迁移

### 更新代码

纯文档提交不要求停止当前队列。运行时变更先安排维护窗口：`stop`，等待 `running=false`，保留批次和配置，再在干净工作区更新对应分支。

```bash
git fetch origin
git pull --ff-only
bash scripts/verify-install.sh
```

有未提交改动时先核对并保存，不使用 `reset --hard`、强制 checkout 或覆盖安装解决分歧。更新后重启需要加载新代码的页面服务，再按原批次续跑。worker 的 `adapter_sha256` 可与 `scripts/crm_enrichment.py` 当前哈希对照；已经加载的进程不会因 Git 更新自动更换实现。

提交前只暂存明确的源文件和文档，检查 `git diff --cached --name-only`、`git diff --cached`，确认没有队列、凭据或业务快照，再普通 push。不要 force push 当前工作分支。

### 回退

回退代码与恢复 CRM 数据是两件事。已有写入不会随 Git 回退撤销；需逐条依据旧值、实际写入和当前业务变更处理。不要退回仍执行低分软删除的旧版队列；保留当前数据保护规则。已合并公司、后来转移联系人、人工更新字段必须保留，不盲目执行历史恢复 SQL。

### 迁移到另一台 Mac

本次仅交接 Git 内容，现有队列留原机。若以后明确安排迁移正在运行的队列：先停原机并确认退出；另行安全传输完整批次和所需配置，不通过 Git 或普通聊天发送；重建 `.venv`，安装本机 Hermes/AnySearch，更新 `settings.json.crm_env` 和 `latest.json.run_dir` 等绝对路径。保留冻结快照及其哈希、CRM 目标指纹，不通过编辑它们绕过校验。旧 PID、页面端口信息不是新机运行状态。

移机后先离线验收，再核查实际输入、模型、Key 来源、代理、缓存与页面证据。另一台 Mac 全流程有效率下降不一定是评分变差：本项目有本机抓取、AnySearch 提取、缓存及失败恢复，逐层区分。具体步骤见 [安装文档的跨 Mac 排查](INSTALL-CODEX.md#同一测试集在另一台-mac-检索失败增多)。

## 故障处理

| 现象 | 先查 | 处理 |
| --- | --- | --- |
| 全部 Key 额度耗尽 | `quota-alert.json`、脱敏池状态 | 页面添加备用 Key，或充值后恢复可用，再续跑；不要自动解除已知耗尽状态 |
| Key 页无法打开 / 端口占用 | `key-ui.json`、对应进程、`lsof -nP -iTCP:54101 -sTCP:LISTEN` | 确认旧页面进程身份；用空闲端口启动，勿误停其他服务 |
| `Invalid port: ':1'` | 子进程继承的 NO_PROXY/no_proxy | 当前版本已将 IPv6 `/128` 单地址范围等价规范化；核对是否加载新代码，不必因此换 Key |
| `AnySearch CLI unavailable` | 固定 CLI 路径、Node、安装哈希 | 按 INSTALL-CODEX 恢复固定版本，不替换为未经验证的 CLI |
| `Hermes executable is unavailable` | `~/.local/bin/aceler-memory` | 按安装文档生成 profile 包装命令 |
| 模型认证错误 | profile `.env` 中变量是否非空、实际 provider | 在本机修复对应凭据，不打印值；不要改评分规则 |
| 连续 10 个技术失败暂停 | `worker.log`、`error.json`、模型和翻译审计 | 先查共享故障，修复后续跑；未确认主体仍属失败 |
| 无可信页面 / 主体未确认 | input-records、anysearch-meta、证据链接、代理与缓存 | 保留原始结果，对齐输入后比较，不将关联主体直接视为目标 |
| 中文翻译 / 字段适配未通过 | `proposal.json` 和模型输出 | 队列拒绝回填；核心 valid 与 CRM 写入成功是不同状态 |
| `CRM target changed` / 快照哈希变化 | 配置来源、manifest、snapshot | 查错库、错误批次或被修改文件，不重写指纹放行 |
| Level / 身份 / 字段冲突 | 各公司 `apply.json` / `invalidation.json` | 人工复核，不能自动覆盖 |
| `interrupted` / 旧 PID 仍在文件中 | 文件锁、实际进程、日志、检查点 | 确认没有在途旧 worker 后 resume，不直接删除锁文件 |
| 无 CRM 配置启动失败 | 是否误用无参数抽样入口 | 选择 JSON API 或 `--selected-file` |

实际网络路由可能受 macOS 系统代理影响，不能只看终端 HTTP_PROXY。不要复制另一台机器的代理端口。缺少底层日志时，不凭最终“未找到可信证据”一句话断定网络、Key 或模型故障。

## 验收与指标

基础验收用 `bash scripts/verify-install.sh`。只运行代码测试时必须显式列模块；本项目存在同名模块/包，避免直接用 `unittest discover`：

```bash
.venv/bin/python -m unittest \
  company_research_trial.test_company_research_trial \
  company_research_trial.test_dashboard \
  company_research_trial.test_research_api \
  company_research_trial.test_orchestration \
  company_research_trial.test_structured_evidence \
  company_research_trial.test_structured_evidence_pilot \
  company_research_trial.test_semantic_decision_validation \
  company_research_trial.test_crm_enrichment \
  company_research_trial.test_anysearch_key_pool

.venv/bin/python skill/aceler-company-research/scripts/validate_assessment.py --self-test
```

2026-09-11 Key 池版本通过上述 168 项测试；自动切换测试模拟额度响应，不代表已经真实耗尽每个备用 Key。真实上线是否发生切换，应看脱敏池状态和实际请求记录，不以页面可打开代替证明。

评估以人工“跟进 / 不跟进”与模型 `match.follow_up` 对照：

- 召回率 = TP / 全部人工正例，含不可评分的人工正例在分母中。
- 精确率 = TP / (TP + FP)。
- 准确率 = (TP + TN) / 全测试集数量，失败不会从分母删除。
- 有效率 = valid / 总数，衡量完成情况，不能当作准确率或 AnySearch API 成功率。

| 历史验收 | 有效结果 | 召回率 | 精确率 | 准确率 | 解释 |
| --- | --- | --- | --- | --- | --- |
| 2026-09-04 固定证据 100 家 | 100/100 | 91.07% | 82.26% | 84.00% | 语义 A/B，未重新实时检索 |
| 2026-09-07 100-4 实时全流程 | 100/100 | 88.57% | 80.52% | 77.00% | 人工正/负例 70/30 |
| 2026-09-07 100-3 原流程 | 98/100 | 83.93% | 83.93% | 81.00% | 含缓存和本机页面抓取，失败未补跑替换 |
| 2026-09-10 官网优先试验 | 20/20 | 80%→70% | 80%→87.5% | 80%→80% | 请求 132→134，未推广 |

当前保留原检索路线，不能自动启用已撤回的官网优先试验。历史质量门槛为召回率 >80%、精确率 ≥75%；不同样本和证据方式不可直接互换。未标注 CRM 队列不能用于宣称当前准确率。完整角色编排、评分细则、回放限制和历史证据说明见 [背调链路与历史验收](docs/research-behavior.md)。

## 代码和文档导航

| 位置 | 责任 |
| --- | --- |
| [INSTALL-CODEX.md](INSTALL-CODEX.md) | 固定依赖、完整 profile 安装、联网冒烟、跨 Mac 自检 |
| [docs/crm-enrichment.md](docs/crm-enrichment.md) | 队列操作、字段规则、检查点、Key 池 |
| [docs/research-behavior.md](docs/research-behavior.md) | 检索/Agent/validator 边界与历史实验 |
| `company_research_trial/company_research_trial.py` | 生产检索、证据、模型调用、校验和报告 |
| `research_api.py` / `dashboard.py` | 来源中立单公司接口 / 结果看板 |
| `orchestration.py` / `agent_contracts.py` | Evidence → Router → Lead → Recall → Arbiter 编排与数据契约 |
| `anysearch_key_pool.py` / `anysearch_bridge.js` | 持久化 Key 切换 / 保留调用方 Key 优先级的 Node 包装 |
| `scripts/crm_enrichment.py` | 冻结清单、实时范围检查、写入、后台运行、页面 |
| `scripts/semantic_decision_validation.py` | 人工标注测试集评估 |
| `scripts/verify-install.sh` | 离线安装与回归验收 |
| `skill/aceler-company-research/` | 仓库固定 Skill、26 项产品目录和 validator |
| `config/hermes/aceler-memory/` | 通用业务记忆与 profile 模板，不含运行密钥 |

接手顺序：核对提交和运行范围 → 安装外部依赖 → 离线验收 → 一家公司联网验证 → 明确选择独立背调或 CRM 批次。不要通过修改 Skill、降低身份门槛、改人工标签或覆盖历史结果让验收“通过”。
