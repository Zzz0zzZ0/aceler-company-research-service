# CRM 批量补充与中断续跑

使用仓库 `.venv`、既有 AnySearch 和 MiniMax-M3 背调链路，无额外框架。命令从任意工作目录都可调用；下文以仓库目录为当前目录。

## 筛选和字段规则

- 公司 Source 为 Isales，且无未删除联系人，或所有未删除联系人的 Life Cycle 均为三级（未回复/未联系）。不另要求公司 Level 为三级。
- industry、rating 仅补空值，保留已有值。
- background 用本次证据评估旧文：没有实质新增事实则保留；有新增或更正事实时，在原文后追加带日期和来源的简短中文摘要。原文完整保留，空白字段直接填摘要。每项判断保留理由，不将采购推测或评分推理写成背景事实，完整商业分析保存在 `research-report.md`。
- 行业从 CRM 现有枚举按实际主营业务语义选择；无法确认时不强填“其他”。
- Rating 使用 validator 的总匹配分：0–19→1 星，20–39→2 星，40–59→3 星，60–79→4 星，80–100→5 星。
- 背调失败、主体不确定、中文翻译失败或字段适配未通过校验时不写入。待复核与技术失败单独记录。

## 极低相关度公司删除规则

本批已获授权：背调结果 `status=valid`、validator `valid=true`、主体 `identity_status=confirmed`，且匹配度 **低于 20 分**时，直接对 CRM 公司执行软删除，不再调用中文翻译和字段适配。20 分不删除。失败结果即使占位分数为 0，也绝不据此删除；主体不确定的结果同样保留。

`--apply` 同时启用字段补充和上述软删除；`--dry-run` 只标记 `low_fit`，不删除。此前已完成字段补充的公司也会复用有效背调按新规则处理。只设置公司 `deletedAt` 和更新时间，不删除联系人。删除前再次检查 Isales/全部联系人三级的范围、身份及三项字段是否被他人修改；有冲突则跳过。

`deletion-intent.json` 在提交前持久化删除前值、有效评分、研究文件哈希和数据库生成的删除时间；`deletion.json` 在提交后记录回执。提交后中断可通过唯一删除时间识别已经完成的删除，续跑不重复执行。原数据保留在数据库和本地备份中，可据审计信息恢复。`deleted_low_fit` 是已软删除数，`deletion_*_changed` / `deletion_conflict` 是未删除的冲突项。

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

## 更换 AnySearch Key 并续跑

额度耗尽暂停后，执行 `scripts/crm-enrichment key-ui`，打开命令输出的本机网址。输入框隐藏密钥，点击“保存 Key 并续跑”后自动从当前检查点恢复，范围、并发和写入模式沿用本批设置。页面同时显示进度。任务正在运行时拒绝换 Key，请先 `stop` 并等待退出。

本机页面仅监听 `127.0.0.1`，校验 Host/Origin；密钥经请求体提交，不进入 URL 或日志。复用仓库既有配置写入逻辑，将 Key 原子保存到 `config/local.env`，保留其他配置、限制文件权限，并让新进程使用新 Key。`key-update.json` 仅记录保存时间，不保存密钥。配置提交不等于验证额度，新 Key 无额度时仍会自动暂停。

Key 页面网址和进程号保存在批次的 `key-ui.json`；同一批次重复执行命令返回已有页面。若在终端前台启动页面，关闭该终端只会停止输入页面，已启动的背调 worker 独立运行。

## 检查点和重复写保护

每家公司目录下保存 `result.json`、翻译结果、`proposal.json`、`write-intent.json`、`apply.json` 和引用证据。文件用临时文件、fsync 和原子替换落盘。

- 已写入或明确跳过的公司不再背调。
- 已完成背调但尚未适配/写入时，复用现有结果继续下一步。
- 技术失败在续跑时重试；主体不确定等 `review` 项保留待复核，不反复收费重试。
- 中断时尚未完成的背调可能重跑该公司；完成项不重跑。
- 写入前锁定公司行，检查名称、网址等身份是否变化、联系人是否仍符合范围、待写字段是否仍等于备份原值。人工修改发生冲突时跳过。
- UPDATE 再次检查生命周期筛选条件，且用 RETURNING 核对写入值。只写三项业务字段和更新时间，不变更来源、生命周期或联系人。
- 数据库已提交但本地回执未保存时，续跑会发现字段已等于目标值，记为 `already_applied`，不重复覆盖。
- 连续 10 个技术失败会暂停分派，保留检查点；排除服务或网络故障后执行 `resume`。

本队列强制启用 `ANYSEARCH_STOP_ON_QUOTA=1`：AnySearch 返回明确额度/余额/积分耗尽错误时立即中止检索重试和公共搜索回退，停止派发新公司，保存 `quota-alert.json` 和 `STOP`，并请求 macOS 本机通知。已发出的在途请求不能撤回，已取得完整证据的在途任务可以完成。额度错误不会转成低相关度或被删除，也不等待连续 10 次失败。普通 HTTP 429 限流不冒充额度耗尽。

`status` 显示暂停原因及通知提交结果，日志保留同一原因；系统通知的实际显示取决于 macOS 通知权限和专注模式。恢复额度后手动 `resume`，旧提醒归档至 `alerts/`，本次因额度而中断的公司重新尝试。其他背调入口维持原有额度回退行为，严格停止模式只由本队列强制启用。

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
