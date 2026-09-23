# auto-crypto

空投自动参与实验：先验证云端调度、数据库和模拟预算，随后研究具体活动。

## 当前状态
这是**模拟执行基础版本**，不是已上线的赚钱机器人。Cloudflare Worker 每 5 分钟运行一次，将心跳写入 D1 数据库；`/status` 显示最近心跳、任务数和模拟费用。没有活动发现、模型调用、钱包签名、链上交易或收益。

## 云端部署

- Cloudflare Workers Free；D1 数据库 `auto-crypto-sim`。
- GitHub 连接后，仓库根目录的 `wrangler.jsonc` 用于部署。
- Worker 名称必须是 `auto-crypto-simulation`；构建命令可留空，部署命令为 `npx wrangler deploy`。
- `GET /status` 是公开的只读状态页，无写入接口。首次访问或定时运行会建表。
- Cron 变更可能需要几分钟生效。数据库中 `state.heartbeat` 是实际运行证据。

Cloudflare Dashboard 中可以在 D1 数据库的 Console 手动插入一个**模拟任务**：

```sql
INSERT INTO jobs (id, cost_cents) VALUES ('demo-1', 5);
```

下一次定时运行会将它标为 `simulated` 或 `rejected_budget`。重复 ID 不会被重复插入或扣算。任务金额只用于验证限制，不代表真实 U、手续费、空投资格或收益。

暂停：在 D1 Console 执行 `INSERT INTO state (key, value) VALUES ('paused', '1') ON CONFLICT(key) DO UPDATE SET value='1';`。恢复：把值改为 `0`。状态可在 `/status` 查看。

## 本地验证

需要 Node.js 18+，无运行时依赖：`node --test`。仓库保留了原 Python SQLite 模拟原型，可用下面的命令验证；Cloudflare 不运行 Python 文件。
```sh
python3 -m unittest discover -s tests -v
python3 worker.py enqueue --id demo-1 --cost-cents 5
python3 worker.py once
python3 worker.py status
```
金额单位为模拟美元分，仅用于验证预算机制，不是链上代币单位。
任务在本机创建时默认写入 data/state.db；不要提交数据库。

## 实盘前必须完成

1. 确认用户所在地区、交易所、活动及 API 服务的实际资格；部署地点不改变资格。
2. 找到允许自动化参与的具体活动并核对官方条款、真实投入、费用和退出路径。
3. 增加数据来源、失败告警、独立小额钱包及隔离签名；模型不能直接持有密钥。
4. 逐一验证权限、幂等和实际资金上限，再启用任何真实交易。

目前不得把 `/status` 中的模拟金额当作盈利或真实花费。
