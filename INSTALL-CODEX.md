# 在另一台 Codex 上精确复现

本文用于在一台新的 macOS/Linux 机器上复现当前公司背调服务。目标不是“代码能启动”，而是让影响结果的仓库规则、Hermes 版本、模型配置、完整业务记忆、AnySearch 版本和调用方式全部一致。

本次只随 Git 交付代码、测试及文档，不交付原机当前队列、运行结果、恢复快照或密钥。日常启动、Key 池、维护和嵌入宿主项目的完整入口见 [README](README.md)。

## 复现基线

| 部件 | 固定值 | 验收依据 |
| --- | --- | --- |
| 本仓库 | 与基准机器相同的完整提交号 | 两台机器的 `git rev-parse HEAD` 一致 |
| 公司背调 Skill | 随仓库提交固定 | `.agents/skills/aceler-company-research` 可读 |
| Hermes Agent | `0.20.4` | 上游发布提交 `7e05e9080b2e46cd35e6f0caa016360301258823` |
| Hermes 服务模型 | `MiniMax-M3` | 服务显式传入 `--model`；联网结果 `usage.model` |
| Hermes provider | `minimax-cn` | 服务显式传入 `--provider`；联网结果 `usage.provider` |
| 完整业务记忆 | 当前提交的 `config/hermes/aceler-memory/MEMORY.md` | 与已安装 MEMORY 文件逐字节一致 |
| profile 配置 | 当前提交的 `config/hermes/aceler-memory/config.yaml` | 与已安装配置逐字节一致 |
| AnySearch Skill | `v3.1.0` | 提交 `4d6cef918e9338c9deef43b81ac0f7e22606825f` |
| AnySearch Node CLI | 仓库版本 | SHA-256 `e4944fef758fae860d26b15460f5940f198841c2f965775ec9a2b36092e0edf9` |

当前验收机器使用 macOS、Python `3.14.6`、Node.js `22.23.0`；Hermes 自己的虚拟环境使用 Python `3.11.15`。项目代码要求 Python 3.11 及以上。使用本项目 `.venv/bin/python`；不要直接复制另一台机器的 `.venv`，其解释器链接和路径可能不可用。

profile 的兼容默认模型仍为 `MiniMax-M2.7`，服务会显式覆盖为 `MiniMax-M3`，无需手工修改 profile。`ACELER_HERMES_MODEL` 和 `ACELER_HERMES_PROVIDER` 可覆盖服务配置；精确复现时必须保持 M3 / minimax-cn，并核对实际 usage，不能只查看 profile。

CRM 不是必需依赖。没有 CRM 的机器应从单家公司 JSON、Python API 或固定文件运行，不要伪造 CRM 字段。

## 0. 先判断是全新安装还是已有环境

下面主流程按全新安装编写。若机器上已有以下任一路径，先停止覆盖并备份或在隔离用户中安装：

```bash
test -e "$HOME/.hermes/profiles/aceler-memory" && echo "已有 aceler-memory profile"
test -e "$HOME/.codex/skills/anysearch" && echo "已有 AnySearch Skill"
test -e "$HOME/.local/bin/aceler-memory" && echo "已有 aceler-memory 命令"
```

不要删除同事原有 profile、密钥或运行记录。已有安装可先执行本文“离线验收”；不一致时再决定迁移。

## 1. 安装系统依赖

需要以下命令：

```bash
git --version
python3 --version
node --version
```

macOS 可用 Homebrew 安装缺失项：

```bash
brew install git python@3.14 node@22
```

确保 `~/.local/bin` 在 `PATH` 中。zsh 可加入：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 2. 克隆并锁定本仓库

```bash
git clone --branch codex/crm-enrichment-20260909 https://github.com/Zzz0zzZ0/aceler-company-research-service.git
cd aceler-company-research-service
git rev-parse HEAD
```

以上获得本次交接分支（包含 CRM 队列、联系人保护和 Key 池）；较早的 main 不代表本次交接版本。两台机器对照时，先在基准机器运行 `git rev-parse HEAD`，将其完整输出填入下方变量，再在新机器执行：

```bash
ACELER_REPRO_REF='替换为基准机器的完整提交号'
git checkout --detach "$ACELER_REPRO_REF"
git status --short
```

`git status --short` 应没有输出。后续所有命令默认在该仓库根目录执行。不要使用历史安装文档中的旧 tag 复现交接版本；项目提交号应随每次基准运行记录，不在安装脚本中写死。

## 3. 创建项目 Python 环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

`psycopg` 用于可选的 CRM 抽样与批量补充适配器，但安装固定 `requirements.txt` 能减少机器差异。

## 4. 安装固定版本 AnySearch

生产链路通过仓库内 `anysearch_bridge.js` 调用 `~/.codex/skills/anysearch/scripts/anysearch_cli.js`，因此路径和版本都必须一致。这个外部目录不会随项目 Git 克隆一起安装：

```bash
mkdir -p "$HOME/.codex/skills"
git clone https://github.com/anysearch-ai/anysearch-skill.git \
  "$HOME/.codex/skills/anysearch"
git -C "$HOME/.codex/skills/anysearch" checkout --detach \
  4d6cef918e9338c9deef43b81ac0f7e22606825f
```

验收：

```bash
test "$(git -C "$HOME/.codex/skills/anysearch" rev-parse HEAD)" = \
  "4d6cef918e9338c9deef43b81ac0f7e22606825f"
shasum -a 256 "$HOME/.codex/skills/anysearch/scripts/anysearch_cli.js"
node "$HOME/.codex/skills/anysearch/scripts/anysearch_cli.js" doc >/dev/null
```

SHA-256 必须是：

```text
e4944fef758fae860d26b15460f5940f198841c2f965775ec9a2b36092e0edf9
```

批量复现前在同事本机配置自己的 AnySearch key，并确认它的可用额度。推荐写入被 Git 忽略的项目 `config/local.env`（已有文件时只编辑这一项，不覆盖其他配置）：

```text
ANYSEARCH_API_KEY=<同事自己的密钥>
```

随后执行 `chmod 600 config/local.env`。也支持已安装 AnySearch 的 `.env`，但两台机器须确认实际使用的配置来源。项目加载配置时保留父进程已存在的环境变量；bridge 将非空服务 key 作为 CLI 参数内部传递，优先于 AnySearch 自己的 `.env`。不要提交密钥，也不要将其贴到聊天或截图中。

## 5. 安装固定版本 Hermes Agent

全新机器使用上游 `0.20.4` 的公开发布提交，不使用最新 `main`：

```bash
mkdir -p "$HOME/.hermes"
git clone https://github.com/NousResearch/hermes-agent.git \
  "$HOME/.hermes/hermes-agent"
git -C "$HOME/.hermes/hermes-agent" checkout --detach \
  7e05e9080b2e46cd35e6f0caa016360301258823
cd "$HOME/.hermes/hermes-agent"
./setup-hermes.sh
cd -
```

安装脚本会创建 Hermes 自己的 Python 3.11 环境并询问是否运行 setup wizard。此项目不依赖默认 profile，可在最后一个问题选择 `n`。完成后重新打开终端或执行：

```bash
export PATH="$HOME/.local/bin:$PATH"
hermes --version
```

第一行必须包含 `Hermes Agent v0.20.4`。全新安装还应确认源码提交：

```bash
git -C "$HOME/.hermes/hermes-agent" rev-parse HEAD
```

应输出 `7e05e9080b2e46cd35e6f0caa016360301258823`。不要运行 `hermes update`，否则会偏离本复现基线。

## 6. 创建并安装 `aceler-memory` profile

回到本仓库根目录后执行：

```bash
hermes profile create aceler-memory --no-skills \
  --description "Aceler approved product and industrial-process knowledge"
install -d -m 700 "$HOME/.hermes/profiles/aceler-memory/memories"
install -m 644 config/hermes/aceler-memory/config.yaml \
  "$HOME/.hermes/profiles/aceler-memory/config.yaml"
install -m 600 config/hermes/aceler-memory/MEMORY.md \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

在以下文件中只配置同事自己的 MiniMax 中国区 API 密钥：

```text
~/.hermes/profiles/aceler-memory/.env
```

文件内容至少包含：

```text
MINIMAX_CN_API_KEY=<同事自己的密钥>
```

然后收紧权限：

```bash
chmod 600 "$HOME/.hermes/profiles/aceler-memory/.env"
```

不要把其他 CRM、邮箱或消息发送密钥放进这个 profile。生产代码会过滤传给 Hermes 的环境变量，但 profile 本身仍应最小授权。

确认配置和完整记忆没有被缩减或手工改写：

```bash
cmp config/hermes/aceler-memory/config.yaml \
  "$HOME/.hermes/profiles/aceler-memory/config.yaml"
cmp config/hermes/aceler-memory/MEMORY.md \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

两条命令均应退出 0 且没有输出。验收脚本也从当前仓库文件计算哈希并比较，避免业务记忆更新后安装说明仍引用旧哈希。

`hermes profile create` 应同时生成：

```bash
test -x "$HOME/.local/bin/aceler-memory"
head -n 2 "$HOME/.local/bin/aceler-memory"
```

包装命令必须把调用转发到 `hermes -p aceler-memory`。项目默认只调用这个包装命令，并使用全新的 `--oneshot` 会话；不会复用同事的普通 Hermes 对话历史。

## 7. 让 Codex 自动发现仓库 Skill

仓库已把同一份 Skill 暴露在 Codex 官方的 repo-scoped 目录：

```bash
test -f .agents/skills/aceler-company-research/SKILL.md
```

该路径指向仓库内的 `skill/aceler-company-research/`，不会维护两份可能漂移的副本。Codex 从当前目录向仓库根目录扫描 `.agents/skills`；如果刚克隆后未显示 Skill，重启 Codex，再从本仓库目录打开任务。

直接在 Codex 中调用时可写：

```text
使用 $aceler-company-research 对 Hatria 做公司背调，官网是 https://hatria.com。
```

服务端运行不依赖 Codex 当前对话是否加载 Skill，因为 prompt、参考规则和 validator 都从同一仓库提交读取。repo-scoped Skill 入口是为了让同事在 Codex 中直接调用时仍使用同一规则。

Codex repo-scoped Skill 的目录和自动发现规则见 [OpenAI Codex Skills documentation](https://learn.chatgpt.com/docs/build-skills)。

## 8. 先做零额度离线验收

不要先跑批量背调。执行：

```bash
./scripts/verify-install.sh
```

默认检查当前 checkout 并输出提交号；跨机器精确对照时，还要传入第 2 节记录的基准提交号：

```bash
./scripts/verify-install.sh "$ACELER_REPRO_REF"
```

指定基准时还要求受跟踪文件没有未提交修改。脚本检查版本、哈希、实际服务模型配置、密钥是否非空及本仓库测试，不输出密钥，不调用 AnySearch 网络接口或 MiniMax，不读取 CRM，也不产生生产背调结果。离线通过不代表网络、额度或密钥认证已通过。

通过标准：

- 仓库提交与指定基准一致（如指定），AnySearch commit 和 CLI 哈希一致；
- Hermes 为 `0.20.4`；
- 服务调用配置为 MiniMax-M3 / minimax-cn；
- profile 配置和完整 MEMORY 哈希一致；
- `aceler-memory` 包装命令存在；
- profile `.env` 中存在非空 `MINIMAX_CN_API_KEY`，但值不会输出；
- validator 自检为 `6/6`；
- 项目全部七个显式测试模块通过（避免同名模块/包导致 discovery 导入冲突）；
- Python 编译检查通过。

任何一项失败都不要开始联网批量测试。

## 9. 单家公司联网验收

离线验收通过后，先只跑 1 家、不接 CRM：

```bash
printf '%s\n' '{"name":"Hatria","website":"https://hatria.com"}' \
  | .venv/bin/python -m company_research_trial.research_api \
  > /tmp/aceler-research-smoke.json
```

检查返回，不要只看退出码：

```bash
.venv/bin/python -m json.tool /tmp/aceler-research-smoke.json | sed -n '1,120p'
```

验收至少包括：

1. 顶层 `status` 是 `valid`；若为 `failed`，先读 `errors` 和该次输出目录，不能手工改成通过。
2. `assessment.sources` 中的 URL 必须来自本次 AnySearch 证据包。
3. `score`、`level`、产品名和工艺判断通过仓库 validator。
4. 推测仍有明确的证据状态或待确认问题，不能伪装成已确认事实。
5. 展示文本以中文为主，但产品专名、公司/人名、牌号、工艺缩写、数字和单位可保留原文。
6. `usage.model` 为 `MiniMax-M3`，`usage.provider` 为 `minimax-cn`；输出目录内的原始 Hermes、验证及适用的本地化审计文件存在。

联网结果会随网页变化而变化，所以“精确复现”保证的是同一执行逻辑、模型配置、记忆、检索器和规则，不承诺未来网页内容和模型采样逐字一致。排查检索差异时保留实时检索，记录各自的网络、缓存和调用情况；仅比较后续语义判断时，才给两台机器使用同一份已保存证据包、相同输入、并发和 reasoning 参数，并标明是语义 A/B。

## 10. 启动看板

启动看板：

```bash
.venv/bin/python -m company_research_trial.dashboard
```

默认监听 `0.0.0.0:8766`，本机入口为 `http://127.0.0.1:8766/`，应在可信局域网使用。只允许本机访问时显式指定：

```bash
.venv/bin/python -m company_research_trial.dashboard \
  --host 127.0.0.1 --port 8766
```

## 11. 可选 CRM 只读抽样

没有 CRM 就跳过本节。单家公司 API、固定文件和看板新建背调均不需要 CRM。

确需从 Twenty CRM 抽样时：

```bash
test -f config/local.env || cp config/local.env.example config/local.env
chmod 600 config/local.env
```

只在同事本机填写所需连接值。该文件已被 Git 忽略。CRM 查询使用只读事务；不要把 CRM 当作完整事实源，也不要因为 CRM 字段缺失降低公司匹配分。

## 12. 可选 CRM 写入与 Key 池

先完成无 CRM 冒烟。需要批量补充时，再按 [README 的 CRM 启动步骤](README.md#crm新建批次) 配置数据库、冻结新清单并验证 dry-run。`--apply` 同时启用字段回填和低于 20 分公司标无效，保留联系人，不再删除公司。Key 池由本机 `scripts/crm-enrichment key-ui` 管理，最多 20 个 Key，全部耗尽才暂停。

原机当前队列不通过 Git 迁移，不要在新机创建同范围写入批次与原机并跑。未来如单独安排迁移，按 [迁移说明](README.md#迁移到另一台-mac) 处理完整批次、独立密钥传输、本机依赖和绝对路径。

## 常见偏差与定位

### 同事准确率明显低于基准

依次核对：仓库提交和工作区、Hermes `0.20.4`、usage 中实际的 MiniMax-M3 / minimax-cn、profile 与仓库文件是否一致、AnySearch commit、Skill 路径和离线测试。区分检索失败、模型调用失败和评分差异，不从“通过率降低”直接推断模型变差。

### 同一测试集在另一台 Mac 检索失败增多

- 比较运行目录实际保存的 `input-records.json`，包括每家的 `name` 和 `website`；同名 Markdown 文件不足以证明输入一致。当前 CRM 批量入口要求八列（含地址），且网址应是裸 HTTP(S) URL。七列文件须在副本中补空地址列，Markdown 链接须先转换为其真实链接地址；保留原文件、公司和人工标签。
- 对比 `anysearch-meta.json` 中的 `cache_hit`、`local_extracted_urls`、`error`、`selected_urls`。本流程优先在本机抓取网页，再尝试 AnySearch extract；整体有效率不是 AnySearch API 成功率。缓存位于被忽略的 `outputs/anysearch-cache/`，有效期七天，不会随 Git 克隆复制。
- 普通请求会在主检索失败后自动尝试一轮语义备用检索；已有证据不触发扩展。成功恢复可见 `mode=failure_recovery` 与 `recall_recovery.primary_error`。仅关联主体或主体不确定仍失败，不能为凑有效数放行。`call_counts_scope=recovery_only` 的计数不含失败主检索的未知开销；联网结果和完整日志需要一起核对。
- 核对外部 AnySearch CLI、Node 路径、key 来源及额度。`config/local.env`、`.venv/`、AnySearch 外部安装和系统网络配置均不包含在 Git 仓库中。
- Python 会读取 macOS 系统代理，不能只看终端的 `HTTP_PROXY`。用下面命令查看代理端点，不输出认证信息；不要照搬另一台机器的端口，须确认本机实际运行的代理服务。

```bash
.venv/bin/python - <<'PY'
from urllib.request import getproxies
from urllib.parse import urlsplit
for kind, value in getproxies().items():
    if kind != "no":
        proxy = urlsplit(value)
        print(kind, proxy.scheme, proxy.hostname, proxy.port)
PY
```

失败公司的 `result.json` 可能只有 `AnySearch found no trusted substantive company page`，没有保存底层 metadata。这是最终检索失败信号，不能单凭它断定网络、认证或网页内容中的哪一层出错。保留失败批次，先用同一家输入对照两台环境；未经对齐不要人工改结果或用补跑结果替换原始基线。

### `AnySearch CLI unavailable`

确认文件位于固定路径：

```bash
test -f "$HOME/.codex/skills/anysearch/scripts/anysearch_cli.js"
```

本项目当前不是从 Codex UI 动态寻找 AnySearch，而是直接执行该路径。

### `Hermes executable is unavailable`

确认：

```bash
test -x "$HOME/.local/bin/aceler-memory"
hermes profile alias aceler-memory
```

第二条命令用于重新生成 profile 包装命令。

### MiniMax 认证失败

只确认 profile `.env` 中变量名和非空状态，不要把值贴到终端日志或聊天中：

```bash
grep -Eq '^MINIMAX_CN_API_KEY=.+$' \
  "$HOME/.hermes/profiles/aceler-memory/.env"
```

### 没有 CRM 配置

不要直接运行无参数的批量 CLI。使用第 9 节 JSON stdin、Python API、看板单家公司入口或 `--selected-file`。

## 给同事 Codex 的交接提示词

可将下面整段发给对方的 Codex：

```text
请在一个新目录克隆 https://github.com/Zzz0zzZ0/aceler-company-research-service 的 codex/crm-enrichment-20260909 分支，并按当前 INSTALL-CODEX.md 安装。若提供基准机器的完整提交号，checkout 到同一提交，并把该提交号传给 scripts/verify-install.sh 验收；不要使用历史安装文档中的旧 tag。保留仓库完整 MEMORY 和 profile；服务会显式使用 MiniMax-M3 / minimax-cn，不需改动 profile 的兼容默认模型。不得修改 Skill、validator、检索、重试或评分规则。先做离线验收，只汇报版本、提交、哈希和测试结果，不输出密钥。离线通过后，按文档跑 1 家 Hatria 联网 smoke test 并核对实际 usage。不要连接或写入 CRM，不要发送消息，不要批量运行。若复现失败，保留原始结果并对照实际输入、外部 AnySearch 安装和本机代理；不要人工改判或扩大补跑。
```

## 完成定义

只有以下三层同时通过才算复现完成：

1. **安装一致**：提交、Hermes、AnySearch、profile 和 MEMORY 均通过版本/哈希检查；实际服务模型/provider 一致。
2. **代码一致**：validator、自测、单元测试和编译检查全部通过。
3. **调用一致**：先用无 CRM 的 1 家输入成功生成可追溯的 `valid` 结果，再决定是否扩大测试。

“Codex 能看到仓库”“Hermes 能回答问题”或“页面能打开”都不足以证明精确复现。
