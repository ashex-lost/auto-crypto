# 接入清单：审阅通过后使用，现在不部署

最终需要两个 Cloudflare Workers、D1 数据库和签名 Worker 的 Durable Object。不需要在线聊天室，部署之后不依赖个人电脑持续开机。

## 主 Worker

- ADMIN_TOKEN：控制台随机访问令牌，32–256 字符，存 Secret。
- MODEL_API_KEY：合法可用的模型 API 密钥，存 Secret；订阅不是通用 API 账户。
- EXECUTION_TOKEN：两个 Worker 相同的内部调用令牌，与批准令牌不同，存 Secrets。
- SETTINGS_JSON：预算、地区资格、活动配置；以私有配置/Secret 保存，不提交公开仓库。
- TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID：选择 Telegram 后再接入；否则仅控制台事件。
- DB：现有 D1 binding；EXECUTOR：指向独立执行器的 Service Binding。

SETTINGS_JSON 的完整字段以 src/config.py 为准：费用/本金上限默认 0，固定托管和搜索数据费用默认未知，provider_eligible=false，vaults=[]。这不是可以开始花钱的默认配置。

每个 vaults 条目需要：id、opportunity_id、chain_id、vault、asset、asset_symbol、asset_decimals、principal_usd_micro、amount_raw、min_claim_raw、stop_loss_bps、eligibility_reviewed、automation_allowed、terms_evidence_url、costs_usd_micro。

costs_usd_micro 明确填写 trading/slippage/bridge/exit，可附 ai/opportunity_cost。核查后确认没有某项操作才能填 0；未知不能填 0。资产单位与本金预算要匹配。登记条目只表示技术与条款已审查，不等于批准该轮投资。

## 签名 Worker

- OWNER_TOKEN：只在签名 Worker 的 Secret 中保存；用户批准时输入，主程序不持久保存。
- WALLET_PRIVATE_KEY：仅存签名 Worker Secret。使用独立实验钱包，不使用主钱包助记词，不发送到对话。
- RPC_URL：选定链的 HTTPS RPC，含密钥时同样存 Secret。
- EXECUTOR_CONFIG_JSON：独立限额与已审查合约名单，私有保存。

EXECUTOR_CONFIG_JSON 必需字段：

| 字段 | 含义 |
|---|---|
| chain_id | 当前支持 1 或 56 |
| confirmations | 3–64，按链风险选；不能机械沿用测试最低值 |
| gas_limit | 单笔 Gas 上限 |
| max_gas_price_wei | 最高 Gas 单价，十进制字符串 |
| lifetime_fee_cap_wei | 累计 Gas 上限，十进制字符串 |
| max_gas_usd_micro | 7 笔交易的保守 Gas 美元预算 |
| gas_usd_quote_expires_at | 报价有效期，UTC Unix 秒 |
| vaults | 经过审查的适配条目数组 |

执行器每个适配条目包含 id/reviewed/opportunity_id/asset/vault/distributor/asset_decimals/max_amount_raw，以及 asset_code_hash/vault_code_hash/distributor_code_hash。地址和代码 hash 从正确链核验，不能把 AI 随意生成的字符串填进白名单。

## 之后的部署顺序

仅在用户检查通过后：部署签名 Worker（无公网入口）、数据库迁移、主 Worker、Service Binding，配置 Secrets 和受保护的控制台入口。先不启用 Cron。

验证读取、模拟、通知和批准阻断，再批准最小金额真实方案。完整核对后才开启定时运行。初始可考虑 5 分钟唤醒，来源默认每小时刷新；这是轮询，不承诺秒级抢名额，频率根据实际费用和时效调整。

地区与账户资格由实际服务条款决定，不能通过更换服务器地区或借他人密钥自动解决。
