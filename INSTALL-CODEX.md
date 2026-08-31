# 在另一台 Codex 上精确复现

本文用于在一台新的 macOS/Linux 机器上复现当前公司背调服务。目标不是“代码能启动”，而是让影响结果的仓库规则、Hermes 版本、模型配置、完整业务记忆、AnySearch 版本和调用方式全部一致。

## 复现基线

| 部件 | 固定值 | 验收依据 |
| --- | --- | --- |
| 本仓库 | tag `repro-2026-08-31` | `HEAD` 必须指向该 tag |
| 公司背调 Skill | 随仓库 tag 固定 | `.agents/skills/aceler-company-research` 可读 |
| Hermes Agent | `0.20.4` | 上游发布提交 `7e05e9080b2e46cd35e6f0caa016360301258823` |
| Hermes 模型 | `MiniMax-M2.7` | profile `config.yaml` |
| Hermes provider | `minimax-cn` | profile `config.yaml` |
| 完整业务记忆 | 仓库版本 | SHA-256 `ecccadbc975bad1c70926801d03971227a3afeba775526bfd2f105a8aaa8daa9` |
| profile 配置 | 仓库版本 | SHA-256 `25794c0c7d82bc31e5b218605120b304d523aa35c4d7c1c2fdce141d23bc3d09` |
| AnySearch Skill | `v3.1.0` | 提交 `4d6cef918e9338c9deef43b81ac0f7e22606825f` |
| AnySearch Node CLI | 仓库版本 | SHA-256 `e4944fef758fae860d26b15460f5940f198841c2f965775ec9a2b36092e0edf9` |

当前验收机器使用 macOS、Python `3.14.6`、Node.js `22.23.1`；Hermes 自己的虚拟环境使用 Python `3.11.15`。项目代码要求 Python 3.11 及以上。Python/Node 的补丁版本不同通常不会改变背调语义，但若要排除全部环境差异，应使用上述基线。

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
git clone https://github.com/Zzz0zzZ0/aceler-company-research-service.git
cd aceler-company-research-service
git checkout --detach repro-2026-08-31
```

确认没有拉到后续漂移版本：

```bash
test "$(git rev-parse HEAD)" = "$(git rev-list -n 1 repro-2026-08-31)"
git status --short
```

第二条命令应没有输出。后续所有命令默认在该仓库根目录执行。

## 3. 创建项目 Python 环境

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

`psycopg` 只用于可选的 CRM 只读抽样，但安装固定 `requirements.txt` 能减少机器差异。

## 4. 安装固定版本 AnySearch

生产链路直接调用 `~/.codex/skills/anysearch/scripts/anysearch_cli.js`，因此路径和版本都必须一致：

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

AnySearch 支持匿名低额度。需要更高额度时，只在同事本机创建 `~/.codex/skills/anysearch/.env`：

```text
ANYSEARCH_API_KEY=<同事自己的密钥>
```

随后执行 `chmod 600 "$HOME/.codex/skills/anysearch/.env"`。不要把密钥写进本仓库、聊天记录或安装截图。

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
shasum -a 256 \
  "$HOME/.hermes/profiles/aceler-memory/config.yaml" \
  "$HOME/.hermes/profiles/aceler-memory/memories/MEMORY.md"
```

预期依次为：

```text
25794c0c7d82bc31e5b218605120b304d523aa35c4d7c1c2fdce141d23bc3d09
ecccadbc975bad1c70926801d03971227a3afeba775526bfd2f105a8aaa8daa9
```

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

脚本只检查版本、哈希、密钥是否存在以及本仓库测试，不读取密钥值，不调用 AnySearch，不调用 MiniMax，不读取 CRM，也不产生生产背调结果。

通过标准：

- 仓库 tag、AnySearch commit 和 CLI 哈希一致；
- Hermes 为 `0.20.4`；
- profile 配置和完整 MEMORY 哈希一致；
- `aceler-memory` 包装命令存在；
- profile `.env` 中存在非空 `MINIMAX_CN_API_KEY`，但值不会输出；
- validator 自检为 `5/5`；
- 项目单元测试全部通过；
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
6. `usage` 和输出目录内的原始 Hermes、验证及本地化审计文件存在。

联网结果会随网页变化而变化，所以“精确复现”保证的是同一执行逻辑、模型配置、记忆、检索器和规则，不承诺未来网页内容和模型采样逐字一致。若需要数值 A/B，必须给两台机器使用同一份冻结证据包、相同输入、相同并发和相同 reasoning 参数。

## 10. 启动看板

本机访问：

```bash
.venv/bin/python -m company_research_trial.dashboard
```

默认地址是 `http://127.0.0.1:8765/`。仅在可信局域网和已确认防火墙规则时使用：

```bash
.venv/bin/python -m company_research_trial.dashboard \
  --host 0.0.0.0 --port 8765
```

## 11. 可选 CRM 只读抽样

没有 CRM 就跳过本节。单家公司 API、固定文件和看板新建背调均不需要 CRM。

确需从 Twenty CRM 抽样时：

```bash
cp config/local.env.example config/local.env
chmod 600 config/local.env
```

只在同事本机填写所需连接值。该文件已被 Git 忽略。CRM 查询使用只读事务；不要把 CRM 当作完整事实源，也不要因为 CRM 字段缺失降低公司匹配分。

## 常见偏差与定位

### 同事准确率明显低于基准

依次核对：仓库 tag、Hermes `0.20.4`、MiniMax-M2.7、`minimax-cn`、两个 profile 哈希、AnySearch commit、Skill 路径和离线测试。最常见的“能运行但效果不同”原因是只复制代码，没有复制完整 MEMORY，或者使用了默认 Hermes profile/其他模型。

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
请在一个新目录克隆 https://github.com/Zzz0zzZ0/aceler-company-research-service，严格按 INSTALL-CODEX.md 安装，并 checkout repro-2026-08-31。不得更换 Hermes 模型/provider，不得缩减或总结 MEMORY，不得修改 Skill、validator、证据条数、重试、零分复核、中文本地化或评分规则。先运行 scripts/verify-install.sh；只汇报版本、提交、哈希和测试结果，不输出任何密钥。离线验收全部通过后，才按文档跑 1 家 Hatria 联网 smoke test。不要连接或写入 CRM，不要发送消息，不要批量运行。若任何固定版本或哈希不一致，停止并报告具体差异，不要自行“兼容”或升级。
```

## 完成定义

只有以下三层同时通过才算复现完成：

1. **安装一致**：tag、Hermes、AnySearch、profile 和 MEMORY 均通过版本/哈希检查。
2. **代码一致**：validator、自测、单元测试和编译检查全部通过。
3. **调用一致**：先用无 CRM 的 1 家输入成功生成可追溯的 `valid` 结果，再决定是否扩大测试。

“Codex 能看到仓库”“Hermes 能回答问题”或“页面能打开”都不足以证明精确复现。
