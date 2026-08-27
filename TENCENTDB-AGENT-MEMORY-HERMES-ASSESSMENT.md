# TencentDB Agent Memory 接入 Hermes 背调评估

日期：2026-08-24

## 结论

可以接入，并且官方仓库已经提供 Hermes `MemoryProvider` 适配器，不需要从零设计接口。本机 Hermes 0.20.4 具备相同的 Provider 生命周期和用户插件发现目录，Node.js 22.23.1 也满足官方要求的 Node.js >= 22.16.0，因此静态兼容性较高。

但它主要能提升跨会话规则一致性、历史纠错复用和长上下文管理，不能替代实时网页证据，也不能天然提高公司事实准确率。对当前背调系统，直接开启默认的自动对话捕获有污染风险；建议先做隔离、受控写入的 A/B PoC，不直接切换生产配置。

## 已核实的接入接口

官方 Hermes Provider 是一个 Python HTTP 客户端和进程监督器，连接本地 Node.js Gateway：

- `prefetch(query)` 调用 `/recall`，把召回结果作为有界记忆上下文注入 Hermes。
- `sync_turn(user, assistant)` 在后台调用 `/capture`，保存完成轮次。
- `on_session_end` 调用 `/session/end`，触发会话级处理。
- 另外暴露结构化记忆搜索和原始对话搜索两个工具。
- Gateway 默认使用本地 SQLite；官方也描述了向量召回、BM25/混合召回以及 L0 对话、L1 原子记忆、L2 场景、L3 Persona 的分层结构。

本机现状：

- Hermes 版本：0.20.4。
- 当前 `aceler-memory` profile 仅启用内置 `MEMORY.md`，没有外部 Provider。
- Hermes 支持 bundled 与 `$HERMES_HOME/plugins/<name>/` 两种 Provider 发现路径。
- Node.js：22.23.1。
- 因此可在独立 Hermes profile 中加入官方 `memory_tencentdb` Provider；当前生产 profile 无需先改。

## 对背调效果的可能影响

| 指标 | 预期影响 | 原因 |
|---|---|---|
| 角色标签一致性 | 中等正向 | 可召回已经人工确认的角色判定原则、反例和边界。 |
| 产品映射一致性 | 中等正向 | 可复用“EAF 才允许 Graphite Electrode”等稳定工艺约束。 |
| 单家公司实时事实准确率 | 很小或不确定 | 记忆没有提供新的当期网页证据；错误旧记忆还会误导判断。 |
| 长上下文与重复提示 | 有条件正向 | 只有在少量 Top-K、字符预算明确、替代重复规则注入时才会缩短上下文。 |
| 延迟与成本 | 负向 | 每轮增加同步 recall；自动 L1/L2/L3 提炼还需要额外 LLM 调用。 |

官方公布的性能提升来自 OpenClaw 的连续长任务及 PersonaMem 等基准，不能直接外推为 Hermes 公司背调准确率提升。需要用本项目固定样本自行验证。

## 主要风险

1. **记忆污染**：官方 Provider 默认自动捕获每个完成轮次。若 Hermes 生成了错误产品、角色或否定事实，错误可能被提炼后跨会话召回。
2. **事实过期**：公司业务、产品和组织角色会变化，不能把旧公司事实当永久规则。
3. **证据层级混淆**：对话记忆是“历史判断”，不是网页来源。召回内容必须明确标记为非证据，不能进入 sources 或满足 evidence gate。
4. **上下文反向膨胀**：官方默认 `recall.maxResults=5`，字符预算默认可以不设上限。若不限制召回，可能抵消上下文节省。
5. **成熟度**：官方当前有 2.0.0 稳定版和 2.0.1 beta；近期发布记录仍包含多 Agent 检索为空、记忆丢失等修复，不宜未经隔离直接承担生产判断。

## 推荐 PoC

### 接入 seam

保持现有 `AnySearch -> Hermes -> validator` 主链不变，只在 Hermes 的 Provider seam 上加官方适配器：

```text
实时来源包 -> Hermes
               ^
               | prefetch: 仅召回稳定规则/已审核纠错
         TencentDB Agent Memory
```

记忆不得作为 source，也不得改变“实时网页证据优先”的校验规则。

### 第一阶段：只读召回

- 使用独立 profile、独立数据目录和独立 user/session namespace。
- 不采集普通背调轮次；如果官方配置无法完全关闭 `sync_turn`，在试验适配器中将其置空。
- 只导入人工审核过的稳定规则：角色标签边界、产品工艺硬约束、已确认的典型反例。
- 召回最多 2–3 条，并设置单条和总字符上限。
- 召回块标记为 `policy_memory`，明确“不是公司事实，不可作为来源”。

### A/B 验收

用相同模型、相同 evidence pack、相同提示词对 5 家固定公司分别运行：

- A：当前基线，无外部记忆。
- B：只读召回 TencentDB 记忆。

通过条件：

- 严重事实错误不高于 A；出现任何由旧记忆造成的新严重错误即回退。
- 角色/商业关系或产品映射至少有 1–2 家明确改对，且没有同等数量回归。
- 召回内容没有被列入 sources，没有绕过实时证据门槛。
- 总输入 token 增幅不超过约 10%，P95 延迟增幅记录清楚。
- 关闭 `memory.provider` 后可以无损恢复当前基线。

只有第一阶段通过，第二阶段才允许“人工批准后写入”；仍不建议自动沉淀全部 Hermes 输出。

## 官方资料

- 项目与 Hermes 安装说明：https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/main/README.md
- Hermes Provider 说明：https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/main/hermes-plugin/memory/memory_tencentdb/README.md
- Hermes Provider 实现：https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/main/hermes-plugin/memory/memory_tencentdb/__init__.py
- 发布记录：https://github.com/TencentCloud/TencentDB-Agent-Memory/releases

