# 接口

除 `/` 和 `/healthz` 外，主接口需要 `Authorization: Bearer ADMIN_TOKEN`。POST 只收 JSON，拒绝跨站 Origin。令牌不放 URL/cookie，外部内容按文本展示。

| 接口 | 用途 |
|---|---|
| GET / | 不含账户数据的控制台静态页面 |
| GET /healthz | 进程存活；不等于资金/模型就绪 |
| GET /api/status | 状态、来源、候选、方案、账目、事件和复盘 |
| GET /api/receiver | 只读钱包地址、链和余额快照；不返回私钥 |
| GET /api/task-handoffs | 任务型活动的待处理交接单 |
| POST /api/tick，body {} | 运行一轮；暂停时不新增操作 |
| POST /api/control，body {"paused":true} | 暂停；执行器不可达时明确返回未确认 |
| POST /api/control，body {"paused":false} | 恢复研究，不自动恢复签名权限 |
| POST /api/proposals/{id}/approve | body 为 digest 和 owner_token，批准该版本并启用范围内执行 |
| POST /api/proposals/{id}/resume | body 为 digest 和 owner_token；仅恢复执行器已接受的同一份方案，先恢复研究 |
| POST /api/proposals/{id}/reject，body {} | 拒绝待批准方案 |
| POST /api/task-handoffs/{id}/approve | 批准一份任务交接单；只生成官方页面和步骤，不自动登录、发帖或过验证码 |
| POST /api/task-handoffs/{id}/complete | 用户完成页面动作后提交简短证据，供复盘记账 |

独立执行器无公网路由，通过 Service Binding 访问：

| 接口 | 所需令牌 | 用途 |
|---|---|---|
| POST /preview | EXECUTION_TOKEN | 只读预览和资金检查 |
| GET /state | EXECUTION_TOKEN | 查询状态，不返回已签交易原文 |
| POST /advance | EXECUTION_TOKEN | 推进已经批准的 id，或查原交易结果 |
| POST /pause | EXECUTION_TOKEN | 停止新增签名 |
| POST /owner/approve | OWNER_TOKEN | 验证不可变方案 canonical 文本 |
| POST /owner/check | OWNER_TOKEN | 只验证批准密钥，避免输入错误就占用预算 |
| POST /owner/resume | OWNER_TOKEN | body 的 id 必须等于已批准方案，异常核对后恢复该方案 |
| GET /address | EXECUTION_TOKEN | 返回签名钱包的公开地址；不返回私钥 |

USD 预算单位为微美元：1 美元 = 1,000,000。链上 `*_raw` 为代币最小单位十进制字符串；`*_wei` 为原生币最小单位十进制字符串，不能混用。

通知至少一次投递，超时可能重复，事件 id 可去重。未接入推送时只保存事件，不声称手机已收到。
# 研究字段

`GET /api/status` 增加 `opportunities[].screening`（固定规则原因与参考成本测算）和 `model_runs`（最近 20 次调用的用途、模型、预留和估算实际费用、失败状态）。不返回模型输入快照或密钥。筛选通过不代表获批参与。

`GET /api/readiness` 返回部署验收结果：数据库、令牌、设置、暂停状态、AI 预算、Service Binding、通知和适配器登记。它只读，不部署、不付款、不批准方案；`ready_for_research` 允许继续观察，`ready_for_financial_execution` 只有全部检查和已审查适配器都满足时才可能为 true。

## Galxe 只读活动适配器

| 接口 | 用途 |
|---|---|
| GET /api/adapters | 显示 Galxe 读取能力、配置状态和资格快照；不返回访问令牌 |
| POST /api/adapters/galxe/check | body 为 `{"opportunity_id":"galxe:..."}`；只查询公开活动资格，不登录、不提交、不签名、不领取 |

Galxe 需要官方访问令牌和监控钱包公开地址。令牌只存 Cloudflare Secret。接口可读取活动、状态、人数、截止时间和 `credentialGroups(address)` 资格；官方文档未提供用个人参与者身份完成任务或代领的通用接口，因此资格满足也不会自动记作收益。

## 实际收益、费用与效率（2026-09-30 新增）

| 接口 | 用途 |
|---|---|
| GET /api/metrics | 确定性复盘：来源漏斗、交接单和资金方案状态、模型按用途/型号的调用和费用、各类费用、人工介入次数和分钟、每活动直接净收益、已实现净收益、每人工小时净收益 |
| POST /api/ledger/income | 登记真实到账：`source_ref`、`asset`、`amount_raw`、`decimals`、`usd_micro`、`price_basis`（`stablecoin_1usd`/`exchange_sale_record`/`spot_at_receipt`），必须有 `tx_hash` 或 `evidence`；可附 `opportunity_id`、`received_at` |
| POST /api/ledger/cost | 登记真实费用：`category`（gas/trading/slippage/bridge/exit/claim/ai/search_data/hosting/other）、`usd_micro`，必须有 `tx_hash` 或 `evidence`；计入亏损上限 |
| POST /api/task-handoffs/{id}/complete | 现在可额外提交 `minutes`（实际人工用时，0–1440） |

已实现净收益 = 实际到账收入 − 全部已记录费用（AI/API/托管、Gas 等；未核对账单按预留额）。积分、奖池、APR、未领取奖励不计入。累计“费用 + 未释放风险预留 − 到账”达到 `max_loss_usd_micro` 时自动暂停并发邮件。

所有人工操作（批准、拒绝、恢复、交接完成、登记收支、暂停/恢复）都会写入 `interventions`，用于统计人工介入次数。
