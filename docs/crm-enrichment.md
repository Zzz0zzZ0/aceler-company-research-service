# CRM 批量补充与中断续跑

完整交接入口见 [README](../README.md)。当前队列、快照、结果及密钥不随 Git 推送。

使用仓库 `.venv`、既有 AnySearch 和 MiniMax-M3 背调链路，无额外框架。命令从任意工作目录都可调用；下文以仓库目录为当前目录。

## 筛选和字段规则

- 公司 Source 为 Isales，且无未删除联系人，或所有未删除联系人的 Life Cycle 均为三级（未回复/未联系）。排除公司 Level 为“无效”（`WU_XIAO`），其余不另要求公司 Level 为三级。
- industry、rating 仅补空值，保留已有值。
- background 用本次证据评估旧文：没有实质新增事实则保留；有新增或更正事实时，在原文后追加带日期和来源的简短中文摘要。原文完整保留，空白字段直接填摘要。每项判断保留理由，不将采购推测或评分推理写成背景事实，完整商业分析保存在 `research-report.md`。
- 行业从 CRM 现有枚举按实际主营业务语义选择；无法确认时不强填“其他”。
- Rating 使用 validator 的总匹配分：0–19→1 星，20–39→2 星，40–59→3 星，60–79→4 星，80–100→5 星。
- 背调失败、主体不确定、中文翻译失败或字段适配未通过校验时不写入。待复核与技术失败单独记录。

## 极低相关度公司无效规则

自 2026-09-11 起按用户新策略：背调结果 `status=valid`、validator `valid=true`、主体 `identity_status=confirmed`，且匹配度 **低于 20 分**时，将公司 Level 设为“无效”（`level=WU_XIAO`），不再软删除。20 分、失败或主体未确认的结果不触发此操作；低相关度分支仍不调用中文翻译和字段适配。

`--apply` 同时启用字段补充和标记无效；`--dry-run` 只标记 `low_fit`。变更仅写公司 `level` 和更新时间，保留公司及联系人。写前再次检查 Isales/全部未删除联系人三级（无联系人也可）、身份和业务字段；公司自身 Level 已是一/二级时也跳过降级。有二级及以上联系人（`CUSTOMER`、`INQUIRY`、`QUALIFIED`、`NO_DEMAND`）或其他不符合筛选的联系人时不执行。

`invalidation-intent.json` 在提交前保存旧值、评分、研究文件哈希及数据库时间；`invalidation.json` 在提交后保存回执。提交后中断可根据 Level 和更新时间识别已完成的操作。`invalidated_low_fit` / `already_invalid_low_fit` 表示标记无效；`invalidation_*_changed` / `invalidation_conflict` / `invalidation_level_conflict` 表示跳过。

旧 `deletion*.json` 保留作为历史审计，不再用于发起删除；已恢复公司以 `invalidation.json` 回执优先计数。软删除后的公司行可能被其他流程物理清理，恢复前必须核对当前数据库和备份，不能仅凭旧删除审计宣称整行及关联关系仍然可恢复。

## 公司无效与联系人保护

公司无效不会连带修改联系人生命周期。仅凭公司匹配度低，不能将联系人标为无效；离职、信息错误或联系方式确认失效需要独立证据和单独处理，本适配器不自动判断或修改联系人状态。

- 新建 CRM 批次和默认 CRM 抽样都排除 `company.level=WU_XIAO`。独立文件/API 手工背调不读取 CRM，仍可用于重新评估。
- 固定旧清单每次派发前实时读取 CRM：公司无效记为 `blocked_invalid_company`，未进入 AnySearch 或模型；存在未删除的二级及以上联系人记为 `review_higher_tier_contacts`，转人工复核。其余范围变化记为 `no_longer_eligible`。
- `automation-gate.json` 保留检查时间和原因；这类派发前拦截在下次续跑重新检查，人工恢复公司状态后可再次符合条件。已经完成的公司仍遵循原有检查点。
- 普通补充和低相关度标记在写入前再次检查范围；低分不能覆盖二级及以上联系人的业务事实。任何分支均不修改联系人生命周期。
- 开发信、跟进等其他系统由用户另行处理；本次只应用于本项目，不代表外部系统已拦截。

随时只读核查当前整个固定批次，包括已完成公司：

```bash
scripts/crm-enrichment policy-review
```

生成 `contact-policy-review.json`，含无效公司、联系人数量和二级及以上联系人的公司复核清单；不导出联系人姓名、邮箱或电话。此命令不修改 CRM、队列状态或冻结快照，不调用背调服务；`status` 显示核查时间和汇总。运行时新出现的拦截另见各公司审计和进度计数。

## 首次固定清单

```bash
scripts/crm-enrichment snapshot \
  --run-dir outputs/crm-enrichment/my-batch \
  --crm-env /absolute/path/to/crm.env
```

读取公司身份和三项字段原值，不导出联系人姓名、邮箱或电话。`snapshot.json` 和 `manifest.json` 固定本批清单、原值、行业枚举与目标数据库指纹；再次启动不会重新扩大清单。`outputs/crm-enrichment/latest.json` 指向最近批次，以下命令默认使用该批次，也可显式指定 `--run-dir`。

## 日常启动、停止与续跑

```bash
# 后台处理全部清单并写入；最多 5 家并发
scripts/crm-enrichment start --workers 5 --limit 0 --apply

# 查看持久化进度和进程状态
scripts/crm-enrichment status

# 停止分派新公司，等待正在处理的公司完成后退出
scripts/crm-enrichment stop

# 中断、重启电脑或正常停止后，继续同一清单
scripts/crm-enrichment resume
```

`resume` 保留此前的并发、范围和写入模式。若此前仅跑了小批 `--limit 5`，全量时必须显式用 `--limit 0`；切换模式用 `--apply` / `--dry-run`。`start` 与 `resume` 的续跑行为相同；同一批次有文件锁，重复启动不会产生第二个 worker。

后台进程与终端/Codex 会话分离，日志写入 `worker.log`。macOS 使用系统 `caffeinate -i -w PID` 避免运行时自动空闲睡眠；关机、合盖睡眠或断电仍会中断工作，恢复后执行 `resume`，不声称关机期间仍能运行。没有安装开机自启服务。

## AnySearch Key 自动切换

运行 `scripts/crm-enrichment key-ui`，打开输出的本机管理网址。可保存最多 20 个 Key，查看脱敏标识、可用/耗尽状态和每个 Key 的 CLI 尝试次数，并直接暂停或续跑队列。

- “保存备用 Key”：只保存，不启动队列；Key 池已启用时，可在运行中追加备用 Key。
- “保存并续跑”：保存后按原并发、范围及写入模式继续。同一 Key 重复添加不会清除其耗尽状态。
- Key 充值后，暂停队列并等待退出，再点击“恢复可用”；不用的 Key 可以移除。不会自动猜测每日额度重置时间。
- 当前 Key 明确额度耗尽时，原请求切换到下一个可用 Key。超时、普通 429、无结果和其他错误保持原有处理，不自动耗尽其他 Key。认证失败仍需人工处理。
- 全部 Key 耗尽后，沿用既有 STOP、检查点和 macOS 通知，等待添加可用 Key 或恢复额度后续跑。不自动注册或获取新 Key。

Key 池只对配置它的本项目请求生效，不是通用 HTTP 代理。CRM worker 自动读取 `config/anysearch-keys.json`；独立 CLI/API 需要显式设置 `ANYSEARCH_KEY_POOL_FILE` 为该文件绝对路径。不设置此变量时保留原单 Key 行为。旧 `/key-and-resume` 接口继续兼容，Key 池启用后会将该 Key 加入并恢复可用。

Key 池使用文件锁和原子替换持久化，文件权限 0600，被 Git 忽略。多个并发任务可能已使用同一旧 Key 发出请求；旧请求的失败只标记它实际使用的 Key，不会误标新 Key。网络请求期间不持有文件锁。密钥只传给子进程环境，不出现在命令行、页面响应或审计日志中。

切换以现有 CLI 命令为单位，保持查询内容、检索方式和评分链路。`batch_search` 部分成功后耗尽时，切换会重试整个批次，可能重复已成功查询；每次尝试均计入请求计量。最多连续尝试 20 次，避免无限切换。页面 CLI 尝试次数和请求条数都不等于账单扣点。

页面仅监听 `127.0.0.1`，校验 Host/Origin。Key 经请求体提交，不进入 URL，不回显完整值。首次启用池需要暂停队列；后续新 worker 自动加载。页面网址和进程号保存在批次的 `key-ui.json`；同一批次重复执行命令返回已有页面。可用 `key-ui --port 54101` 指定空闲端口。单独关闭 Key 页面不会停止后台 worker。

## 检查点和重复写保护

每家公司目录下保存 `result.json`、翻译结果、`proposal.json`、`write-intent.json`、`apply.json` 和引用证据。文件用临时文件、fsync 和原子替换落盘。

- 已写入或明确跳过的公司不再背调。
- 已完成背调但尚未适配/写入时，复用现有结果继续下一步。
- 技术失败在续跑时重试；主体不确定等 `review` 项保留待复核，不反复收费重试。
- 中断时尚未完成的背调可能重跑该公司；完成项不重跑。
- 写入前锁定公司行，检查名称、网址等身份是否变化、联系人是否仍符合范围、待写字段是否仍等于备份原值。人工修改发生冲突时跳过。
- UPDATE 再次检查生命周期筛选条件，且用 RETURNING 核对写入值。普通补充分支只写三项业务字段和更新时间；低相关度分支按上述规则修改公司 Level，不变更来源或联系人。
- 数据库已提交但本地回执未保存时，续跑会发现字段已等于目标值，记为 `already_applied`，不重复覆盖。
- 连续 10 个技术失败会暂停分派，保留检查点；排除服务或网络故障后执行 `resume`。

若 Hermes 报 `Invalid port: ':1'`，可能是继承的 `NO_PROXY` / `no_proxy` 中含 IPv6 `/128` 单地址网段，HTTPX 在初始化时将其误解析为端口。模块会在 Hermes/AnySearch 子进程环境中将其转换为等价 IPv6 地址，保留代理地址、其他绕过项和父进程环境。无需更换 API Key 或修改系统代理；修复后重启队列使新代码生效。

本队列强制启用 `ANYSEARCH_STOP_ON_QUOTA=1`。未配置池时，单 Key 返回明确额度/余额/积分耗尽错误即暂停；已配置池时先按池规则切换，全部 Key 耗尽后才中止检索重试和公共搜索回退、停止派发新公司、保存 `quota-alert.json` 和 `STOP`，并请求 macOS 本机通知。已发出的在途请求不能撤回，已取得完整证据的在途任务可以完成。额度错误不会转成低相关度或被删除，也不等待连续 10 次失败。普通 HTTP 429 限流不冒充额度耗尽。

CLI 的 `batch_search` 实际逐条向 `/v1/search` 发请求；当前首轮为 4 条查询，按需补充 2 条，页面提取另计。`search_calls` 是批次成功计数，部分失败不在其中，不能作为账单或完整请求数。批量输出即使退出码为 0，也会检查各 `## Query` 段中的 `Search failed:` 额度错误。

从请求计量功能启用后的新尝试起，`request-usage.json` 按每家公司累计单条查询、提取和 CLI 尝试数，包含失败，续跑保留此前已记录的尝试。此计量在原流程外围进行，不改变检索、评分或删除规则；更早未计量的请求无法补推，记录值不等于账单扣点。

2026-09-10 的官网优先试验未通过门槛，已归档至 `codex/website-first-trial-20260910`，生产仍使用原流程。固定随机抽取的 20 家人工标注样本中：原流程/候选均 20 家有效，召回率 80%/70%，精确率 80%/87.5%，准确率均 80%，请求尝试数 132/134。没有运行完整 100 家扩展验收，没有把候选用于 CRM 写入或删除。完整本地报告位于 `outputs/website-first-validation/20260910/验收报告.md`；`optimization-review.json` 记录本批不采用该试验的决定。

`status` 显示暂停原因及通知提交结果，日志保留同一原因；系统通知的实际显示取决于 macOS 通知权限和专注模式。恢复额度后手动 `resume`，旧提醒归档至 `alerts/`，本次因额度而中断的公司重新尝试。未接入池的其他背调入口维持原有额度回退行为；独立入口显式配置池后，全部耗尽同样抛出额度耗尽错误，但不会替宿主自动创建 CRM STOP 文件。

`progress.json` 的完成数包含写入、保留、待复核和失败，必须结合 `counts` 看实际写入数。`complete` 表示本轮所有公司均已尝试或已有检查点，不表示每家都成功补齐。`paused` / `interrupted` 可续跑。

## 小批验证

```bash
scripts/crm-enrichment start --limit 5 --workers 2 --dry-run
scripts/crm-enrichment status
# 审阅 proposal.json 后，写入同一小批已生成的提案
scripts/crm-enrichment apply --limit 5
```

所有原值和写入前后值都在本地批次目录，供核查及按实际写入字段恢复。目录被 Git 忽略；迁移机器需另行安全复制批次目录，并更新本地 `settings.json` 中 CRM 配置文件路径。目标数据库与快照哈希不一致时拒绝执行。

离线测试：`bash scripts/verify-install.sh`；其中持久化/字段保护测试不访问真实 CRM。
