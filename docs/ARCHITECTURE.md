# 架构与边界

```mermaid
flowchart LR
  Cron[Cloudflare 定时触发] --> Python[Python 调度 Worker]
  Python --> Sources[官方信息收集]
  Sources --> AI[AI 审查]
  AI --> Calc[确定性成本核算]
  Calc --> Proposal[具体方案]
  Owner[用户批准] --> Proposal
  Proposal --> Signer[独立签名 Worker / Durable Object]
  Signer --> Chain[批准的合约操作]
  Chain --> Ledger[实际数量对账与市场估值]
  Ledger --> Review[AI 复盘建议]
  Review --> Sources
  Python <--> D1[D1 状态 / 预算 / 通知]
```

Python Worker 每轮只做有界步骤，不使用常驻进程、线程、进程信号、本地 SQLite 或本地暂停文件。D1 lease 防重叠；模型调用前原子预留费用，失败或超时保留预留，不假定免费，不自动重发同一次分析。

批准摘要绑定链、钱包、合约、金额、份额、Gas、次数、有效期与退出条件。主程序没有签名私钥或批准令牌；批准令牌由用户在该次请求中提供并转发，不持久保存。AI 输入不含任何密钥或令牌。外部网页是资料，不能指定执行 calldata。

签名 Worker 默认没有公网路由。Durable Object 串行处理请求。签名交易原文和 hash 先存盘再广播；恢复只查相同 hash，最多重复广播相同字节，不创建新 nonce。回执达到确认数并核对区块 hash 后才推进；失败交易计 Gas 并停止。

适配器只允许精确 ERC20 授权、ERC4626 mint/赎回和 Merkl 领取。mint 固定份额，授权限制最大资产支出，之后撤销余下授权。领取地址固定为实验钱包，callback data 为空。不允许无限授权、借款、任意调用或向其他地址转钱。

## 必须了解的限制

- ERC4626 redeem 没有最小收款参数，模拟不锁定最终退出价格；止损只是尝试退出的触发条件，不是最大亏损保证。
- 目前只支持 Ethereum/BNB Chain 的普通 Gas，未支持有额外 L1 数据费的链。
- 合约字节码 hash 不能识别所有代理实现/治理参数变化，每个真实金库仍要独立审查。
- 最多一个未完成方案、7 笔交易、2 次领取；本金和奖励同币，没有通用卖币/跨链。领取窗口结束可能仍有后续奖励，不能凭结束状态将其算成已到账。
- 暂停阻止新签名，但已广播交易仍会被确认。失败交易、未确认交易、残余授权需要核对后恢复。
- 云端热钱包存在密钥泄露风险。这里是服务和程序限制，不是链上智能钱包的强制权限。只使用独立小额钱包。
- 复盘只提出建议，不能自动扩大金额、修改白名单或部署代码。

账目区分实际代币数量、原生币 Gas、模型用量费用、托管预算和风险预留。`valuation` 用核对时现货价估值，不是实际换币成交价。缺少价格不猜净收益。全部已关闭仓位可给出扣除费用估值和运行预算的 USDT 净收益估算；美元最终账单未核对前 `net_usd_micro` 为 null。

官方依据：
- [Cloudflare Python 入口](https://developers.cloudflare.com/workers/languages/python/basics/)
- [定时事件](https://developers.cloudflare.com/workers/examples/cron-trigger/)
- [D1 Python 绑定](https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/)
- [ERC4626 标准](https://eips.ethereum.org/EIPS/eip-4626)
- [Merkl 活动接口](https://developers.merkl.xyz/integrate-merkl/opportunities)
- [Merkl 领取](https://developers.merkl.xyz/integrate-merkl/user-rewards)
- [Binance 支持接口边界](https://developers.binance.com/en/docs/introduction)
- [Binance 公共行情接口](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Astra API 规格](https://developers.openai.com/api/docs/models/gpt-6-astra)
