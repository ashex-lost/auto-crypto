# 最终接入清单

这些值可以一次性准备。带“直接填 Cloudflare Secret”的项目不要发到聊天或 GitHub。

## 可以发给我（公开或非密钥）

- 独立实验钱包公开地址：`0x...`
- 首条链：`56`（BNB Chain，默认低手续费）或 `1`（Ethereum）
- 接收代币公开地址和符号：例如 USDC/USDT
- 邮箱收件地址：只用于确认配置，不包含登录密码

## 直接填入 Cloudflare Secret

主 Worker：

- `MODEL_API_KEY`
- `EMAIL_API_KEY`（如使用 Resend）

签名 Worker：

- `WALLET_PRIVATE_KEY`
- `RPC_URL`
- `OWNER_TOKEN`
- `EXECUTION_TOKEN`

## 作为私有变量配置

- `RECEIVER_ADDRESS`
- `RECEIVER_CHAIN_ID`
- `RECEIVER_RPC_URL`
- `RECEIVER_ASSETS_JSON`
- `EMAIL_FROM`、`EMAIL_TO`
- `SETTINGS_JSON`
- `EXECUTOR_CONFIG_JSON`

私钥只进入签名 Worker；主 Worker、模型、通知和接收器永远不需要私钥。

## Galxe 只读任务研究

主 Worker Secret：

- `GALXE_ACCESS_TOKEN`

主 Worker 私有变量：

- `GALXE_SPACE_IDS_JSON`（例如 `["40"]`）

这两个值只打开官方活动读取和公开地址资格查询，不打开任务提交、社交操作或领奖权限。

## SETTINGS_JSON 新增字段（2026-09-30）

| 字段 | 含义 | 建议起点 |
|---|---|---|
| `max_loss_usd_micro` | 累计最大亏损，含 AI/API/托管 | `500000000`（500U） |
| `max_principal_usd_micro` | 单个资金方案本金上限 | `500000000` 以内，首轮建议更小 |
| `participant_region` | 你实际居住/账户注册地区，用于资格核查 | 由你填写 |
| `accounts` | 你真实拥有的单一账户：`binance`/`x`/`discord`/`telegram`/`evm_wallet`/`email`/`github` 设为 true | 按实际 |
| `human_hour_usd_micro` | 你一小时人工时间值多少美元；未填时固定奖励任务的“扣时间后净额”保持未知 | 由你决定 |
| `min_reward_to_risk_bps` | 资金方案“保守净收益 / 最坏损失”下限，0 表示只显示不拦截 | 0 或按复盘调整 |
| `speculative_task_max_minutes` | 抽奖/积分类任务只在零现金成本且预计用时不超过此值时才生成交接单；0 表示只研究 | 0 |
| `report_days` | 确定性复盘报告和邮件的周期（天） | 7 |

私有变量 `DASHBOARD_URL`：邮件中附带的控制台地址（可选）。
