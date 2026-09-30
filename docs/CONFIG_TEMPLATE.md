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
