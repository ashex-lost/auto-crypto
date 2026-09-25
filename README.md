# Auto Crypto：先批准，再参与

目标：搜索适合的空投/明确奖励活动 → AI 审查 → 核算全部成本 → 用户批准 → 自动参与和退出/领取 → 对账复盘。

**这是待审阅的程序版本，尚未部署，没有接入真实模型账户、钱包或获批准的活动。** 程序可以启动；接入具体活动和最小金额验收仍是上线条件。没有合格机会时不交易。

## 实际支持范围

| 环节 | 已实现 | 当前边界 |
|---|---|---|
| 信息收集 | Merkl 官方活动 API 分页采集；Binance 公告链接解析；记录规则版本和故障 | Merkl 已在真实本地 Worker 中抓到活动；Binance 页面本次无法直接读取，明确报错 |
| AI 审查 | Responses API、规则/资格/自动化许可分析、内容缓存、调用前预留费用 | 没有真实模型密钥，未付费调用；缺少条款标未知 |
| 算账 | 本金与支出分开，Gas、交易、滑点、跨链、退出、AI、搜索/数据、托管分列；三种奖励情景 | 费用未知时不生成值得参与的结论；APR 和 25% 压力情景不是收益保证 |
| 批准 | 页面展示具体金额、合约、期限、费用和退出条件；摘要绑定方案版本 | 每个资金方案须批准；AI 无法自行批准 |
| 执行 | 精确授权 → ERC4626 mint → 撤销余下授权 → 持有/赎回 → Merkl 领取 | 首版只支持核查过的 Ethereum/BNB Chain 金库、本金与奖励同币；无借款、跨链或任意兑换 |
| 恢复 | 签名前模拟、广播前持久化签名交易、超时查询相同 hash、确认回执后推进 | 失败交易记账并停止，不盲目重发 |
| 对账复盘 | 实际数量、费用、市场估值、AI 复盘建议 | 市场估算不等于卖出所得；最终美元账单待核对，复盘不能改权限 |
| 通知 | 控制台事件箱、可选 Telegram、重试退避 | 未配置通知渠道时只有控制台，没有实际推送 |

**Binance 稳定币 Launchpool 仍为优先研究类别，但自动申购接口尚未核实，没有编造非官方交易接口。** 链上活动也必须单独核查条款和合约；Merkl 收录不是安全背书或投资推荐。当前活动适配名单为空。

## 每个 Python 文件做什么

| 文件 | 作用 |
|---|---|
| `src/worker.py` | Cloudflare 入口，接收网页请求、批准操作和定时事件。 |
| `src/engine.py` | 总调度，决定本轮收集、分析、执行、对账还是复盘。 |
| `src/collector.py` | 收集官方活动，识别规则变化和来源故障。 |
| `src/analyst.py` | 请 AI 分析，并限制、记录模型费用。 |
| `src/economics.py` | 普通程序计算全部成本和收益情景。 |
| `src/policy.py` | 筛选方案，制作有金额、权限、期限的批准单。 |
| `src/execution.py` | 联系独立执行器；这里没有钱包私钥。 |
| `src/ledger.py` | 区分本金回收、实际奖励、成本与风险预留。 |
| `src/valuation.py` | 给已确认数量补充市场估值；价格缺失标未知。 |
| `src/review.py` | 根据实际记录提出改进建议。 |
| `src/notifier.py` | 保存通知，配置后推送重要事件。 |
| `src/storage.py` | 把状态、预算、批准和事件存进 D1 数据库。 |
| `src/dashboard.py` | 查看状态、批准、拒绝和暂停的网页。 |
| `src/config.py` | 读取预算和接入配置，缺少预算时不调用付费服务。 |
| `src/network.py` | 限时、限大小地请求接口，拒绝自动跳转。 |
| `src/common.py` | 统一检查金额、地址和方案摘要。 |

`executor/` 是单独的 JavaScript 签名程序，使用 EVM 签名库；与 Python 主程序隔离。不是所有部分都塞进一个 Python 文件。

## 你现在先检查什么

先看 [审阅说明](docs/REVIEW.md) 和 [架构边界](docs/ARCHITECTURE.md)。检查通过后，再确定当期活动、配置模型账户/独立钱包/通知和预算，进行最小金额验收。现在不需要往钱包转钱。

配置关闭定时、关闭公网路由、默认暂停、费用预算为零。没有自动部署流水线。上传代码不代表批准上线或花钱。

## 本地验证

需要 Node.js 22+、Python 3.13+、uv 和 pnpm。版本由锁定文件固定。

```sh
uv sync --locked
pnpm install --frozen-lockfile
uv run python -m unittest discover -s tests -v
node --test tests/executor.test.js
pnpm check:executor
node tests/executor_runtime.mjs
pnpm db:local
uv run pywrangler dev --local --test-scheduled --port 8789 -c wrangler.jsonc -c executor/wrangler.jsonc
```

`tests/runtime_smoke.py` 只用于无模型密钥、无资金方案的本地测试；需要文件内注明的测试令牌。它短暂恢复本地研究、读取公开活动，然后恢复暂停，不能对线上服务使用。

`pnpm check:bundle` 和 `pnpm check:executor` 都只做 dry-run 打包，不部署。接入清单见 [SETUP.md](docs/SETUP.md)，接口见 [API.md](docs/API.md)。
