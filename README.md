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

## 文件分工：13 个 Python 文件

整体分成入口、调度、业务、基础服务和独立钱包执行器。财务三个文件已合并，AI 分析与复盘也已合并；数据库格式和批准规则不变。

| 文件 | 小白版作用 |
|---|---|
| `src/worker.py` | 门口：接收你点的批准/暂停，以及定时唤醒。 |
| `src/dashboard.py` | 操作页面：显示活动、费用、账目，让你批准或拒绝。 |
| `src/engine.py` | 总调度：安排本轮搜索、分析、执行、记账或复盘。 |
| `src/collector.py` | 找活动：收集官方信息，检查规则有没有变化。 |
| `src/ai.py` | AI 顾问：参与前分析风险，参与后复盘；记录模型调用费用，没有钱包操作权。 |
| `src/finance.py` | 财务：参与前算是否划算，参与后记真实收支，再按市场价估值。 |
| `src/policy.py` | 规则检查：检查资格、预算和范围，生成需要你批准的具体方案。 |
| `src/execution.py` | 执行联络：把获批方案交给独立钱包执行器，并查询结果。 |
| `src/notifier.py` | 通知：保存待办消息，配置渠道后推送。 |
| `src/storage.py` | 记忆：保存进度、预算、批准和事件，避免重启后重复做。 |
| `src/config.py` | 设置：读取预算、地区资格和已核查活动名单。 |
| `src/network.py` | 网络连接：访问外部接口，限制等待时间和返回大小。 |
| `src/common.py` | 公共检查：检查金额、地址和方案是否被改动。 |

独立的 `executor/` 使用 JavaScript，是钱包执行部分：

| 文件 | 小白版作用 |
|---|---|
| `worker.js` | 验证身份，区分你的批准与程序的普通调用。 |
| `policy.js` | 独立复核金额、合约、次数和有效期。 |
| `engine.js` | 按已批准方案参与、撤销授权、退出和领取，核对交易结果。 |

`wrangler.jsonc` 是 Cloudflare 的运行配置；`migrations/` 是账本表结构；`tests/` 是自动检查；其余依赖及锁定文件确保安装相同版本的工具。完整流程与模块关系见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

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
