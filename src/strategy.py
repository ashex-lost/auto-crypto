"""Expected-value ranking and per-category learning. Pure rules; no network, wallet or model calls.

Iteration rule (deterministic, visible in the console):
  EV = P(paid) x expected payout - cash cost - human minutes x hourly value - AI cost
  P(paid) and expected payout start from category priors you can edit, and move toward what
  actually happened in that category as finished results accumulate (Bayesian shrinkage:
  weight = finished / (finished + PRIOR_WEIGHT)). Raffles are therefore judged as a group,
  never by one lucky or unlucky draw.
"""
import json
from common import Blocked, integer

PRIOR_WEIGHT = 10  # A category needs ~10 finished results before history outweighs the prior.

CATEGORIES = {
    "bounty":         "AI 悬赏/黑客松",
    "onchain_usage":  "未发币项目链上真实使用",
    "fixed_task":     "固定奖励任务",
    "points_deposit": "积分计划/存款奖励",
    "testnet":        "测试网",
    "raffle":         "抽奖任务",
    "points_task":    "积分任务（未公布空投）",
    "exchange":       "交易所活动公告",
    "other":          "其他",
}

# Starting guesses, editable in the console. p = chance of being paid at all; payout in USD when paid.
DEFAULT_PRIORS = {
    "bounty":         {"p": 0.10, "payout_usd": 1000, "weight": 1.0},
    "onchain_usage":  {"p": 0.15, "payout_usd": 300,  "weight": 1.0},
    "fixed_task":     {"p": 0.80, "payout_usd": None, "weight": 1.0},
    "points_deposit": {"p": 0.30, "payout_usd": 20,   "weight": 1.0},
    "testnet":        {"p": 0.05, "payout_usd": 100,  "weight": 1.0},
    "raffle":         {"p": None, "payout_usd": None, "weight": 1.0},
    "points_task":    {"p": 0.05, "payout_usd": 30,   "weight": 1.0},
    "exchange":       {"p": None, "payout_usd": None, "weight": 1.0},
    "other":          {"p": None, "payout_usd": None, "weight": 1.0},
}


def category(opportunity):
    data = opportunity["data"]
    data = json.loads(data) if isinstance(data, str) else data
    if data.get("category") in CATEGORIES:
        return data["category"]
    source = opportunity.get("source")
    if source == "merkl":
        return "points_deposit"
    if source == "binance":
        return "exchange"
    if source == "bounty":
        return "bounty"
    if source == "task":
        kind = data.get("reward_kind")
        return {"fixed": "fixed_task", "raffle": "raffle", "points": "points_task"}.get(kind, "points_task")
    return "other"


def project_key(opportunity):
    """What "similar project" means when one activity rejected your account."""
    import re
    data = opportunity["data"]
    data = json.loads(data) if isinstance(data, str) else data
    source = opportunity.get("source")
    if data.get("adapter") == "galxe_read_v1" and data.get("space_id"):
        return "galxe_space:" + str(data["space_id"])
    if source == "merkl" and data.get("protocol"):
        return "protocol:" + str(data["protocol"])
    if source == "binance":
        m = re.search(r"launchpool|hodler|megadrop|launchpad|airdrop", str(opportunity.get("title") or ""), re.I)
        return "binance:" + (m.group(0).lower() if m else "other")
    if data.get("sponsor"):
        return "sponsor:" + str(data["sponsor"]).lower()[:80]
    return "activity:" + str(opportunity.get("id"))


def priors(s):
    merged = {k: dict(v) for k, v in DEFAULT_PRIORS.items()}
    for k, v in (s.get("category_priors") or {}).items():
        if k in merged and isinstance(v, dict):
            merged[k].update({x: v[x] for x in ("p", "payout_usd", "weight") if x in v})
    return merged


def validate_priors(value):
    if not isinstance(value, dict) or set(value) - set(CATEGORIES):
        raise Blocked("category_priors_invalid")
    for v in value.values():
        if not isinstance(v, dict) or set(v) - {"p", "payout_usd", "weight"}:
            raise Blocked("category_priors_invalid")
        p, pay, w = v.get("p"), v.get("payout_usd"), v.get("weight", 1.0)
        if p is not None and (isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1):
            raise Blocked("category_priors_invalid")
        if pay is not None and (isinstance(pay, bool) or not isinstance(pay, (int, float)) or not 0 <= pay <= 1_000_000):
            raise Blocked("category_priors_invalid")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 <= w <= 10:
            raise Blocked("category_priors_invalid")
    return value


def calibrated(prior, history):
    """Blend the prior with finished results of the same category."""
    n = (history or {}).get("finished", 0)
    if not n:
        return prior["p"], prior["payout_usd"], 0.0
    paid = history.get("paid", 0)
    w = n / (n + PRIOR_WEIGHT)
    p = prior["p"] if prior["p"] is not None else paid / n
    p = (1 - w) * p + w * (paid / n)
    avg = history["income_usd"] / paid if paid else None
    pay = prior["payout_usd"]
    if avg is not None:
        pay = avg if pay is None else (1 - w) * pay + w * avg
    return p, pay, w


# Rough per-transaction gas in USD by chain (manual MetaMask use). Mainnet is costly; L2s are cents.
GAS_PER_TX_USD = {1: 1.5, 56: 0.05, 8453: 0.03, 42161: 0.05, 10: 0.03, 137: 0.02, 59144: 0.05, 534352: 0.05}
DEFAULT_GAS_PER_TX_USD = 0.1
YIELD_TXS = 4          # approve + deposit + withdraw + claim
YIELD_MINUTES = 10     # four MetaMask confirmations and checks
APR_HAIRCUT = 0.5      # APR shown is a snapshot and usually falls
OTHER_TOKEN_HAIRCUT = 0.7


def certainty(basis):
    """How reliable the EV inputs are. Only used to order activities whose EV ties."""
    return {"stated_per_person_reward": 1.0, "pool_with_known_participants": 1.0,
            "apr_snapshot": 0.8, "prior_blended_with_history": 0.8,
            "category_prior": 0.6}.get(basis, 0.5)


def yield_ev(data, s, days):
    """Deposit / liquidity: principal x APR x days, halved for decay, minus gas. Time is reported, not charged."""
    principal = (s.get("default_principal_usd_micro") or 50_000_000) / 1e6
    apr = data.get("apr")
    if apr is None or days < 1:
        return None
    rewards = data.get("rewards") or []
    tokens = {str(t.get("address") or "").lower() for t in (data.get("tokens") or []) if isinstance(t, dict)}
    other = any(str(r.get("address") or "").lower() not in tokens for r in rewards if isinstance(r, dict))
    gross = principal * float(apr) / 100 * days / 365 * APR_HAIRCUT * (OTHER_TOKEN_HAIRCUT if other else 1)
    gas = GAS_PER_TX_USD.get(data.get("chainId"), DEFAULT_GAS_PER_TX_USD) * YIELD_TXS
    return {"gross": gross, "cash": gas, "principal": principal, "minutes": YIELD_MINUTES,
            "days": days, "apr": float(apr), "reward_other_token": other}


def expected_value(cat, facts, s, history=None):
    """Returns expected cash result (time is NOT charged; it is a separate sort key).
    facts: cash_cost_usd, human_minutes, ai_cost_usd, principal_usd and optional
    per_person_usd / pool_usd / winners / participants / yield (from yield_ev)."""
    prior = priors(s)[cat]
    p, payout, learned = calibrated(prior, history)
    basis = "category_prior" if not learned else "prior_blended_with_history"
    per_person = facts.get("per_person_usd")
    pool, participants, winners = facts.get("pool_usd"), facts.get("participants"), facts.get("winners")
    y = facts.get("yield")
    cash = facts.get("cash_cost_usd")
    minutes = facts.get("human_minutes")
    principal = facts.get("principal_usd") or 0
    if y:
        gross, cash, principal, minutes, basis, p, payout = y["gross"], y["cash"], y["principal"], y["minutes"], "apr_snapshot", 1.0, y["gross"]
    elif per_person:
        payout, basis = per_person, "stated_per_person_reward"
        p = 0.8
        gross = p * payout
    elif pool and participants:
        # Your share if everyone is equal; final participation usually ~doubles, so assume that.
        expected_participants = max(participants * 2, winners or 1)
        payout, p, basis = pool / expected_participants, 1.0, "pool_with_known_participants"
        gross = payout
    else:
        gross = p * payout if p is not None and payout is not None else None
    ai = facts.get("ai_cost_usd") or 0
    ev = gross - cash - ai if gross is not None and cash is not None else None
    hours = (minutes or 0) / 60
    return {"category": cat, "p_paid": p, "payout_usd": payout, "gross_ev_usd": gross,
            "cash_cost_usd": cash, "ai_cost_usd": ai, "principal_usd": principal,
            "human_minutes": minutes, "ev_usd": ev,
            "roi": (ev / principal) if ev is not None and principal else None,
            "ev_per_hour_usd": (ev / hours) if ev is not None and hours > 0 else None,
            "basis": basis, "certainty": certainty(basis),
            "history_weight": round(learned, 3), "priority_weight": prior.get("weight", 1.0),
            "yield": y, "score": ev}


DEFAULT_RANK_WEIGHTS = {"amount": 0.4, "hourly": 0.35, "capital": 0.25}


def rank(rows, weights=None):
    """Composite score from percentile ranks (no hourly wage needed):
    0.4 x rank(EV) + 0.35 x rank(EV per hour of your time) + 0.25 x rank(EV / principal).
    Activities needing no time or no capital get the top rank for that part.
    Only EV > 0 is ranked; ties are broken by certainty (1 > 0.8 > 0.6 > 0.5)."""
    w = {**DEFAULT_RANK_WEIGHTS, **(weights or {})}
    live = [r for r in rows if r.get("ev_usd") is not None and r["ev_usd"] > 0]
    def pct(key, value):
        vals = sorted(key(x) for x in live)
        if len(vals) <= 1:
            return 100.0
        below = sum(1 for v in vals if v < value)
        return 100.0 * below / (len(vals) - 1)
    hourly = lambda r: r["ev_per_hour_usd"] if r.get("ev_per_hour_usd") is not None else float("inf")
    capital = lambda r: r["roi"] if r.get("roi") is not None else float("inf")
    for r in rows:
        if r in live:
            r["rank_amount"] = pct(lambda x: x["ev_usd"], r["ev_usd"])
            r["rank_hourly"] = pct(hourly, hourly(r))
            r["rank_capital"] = pct(capital, capital(r))
            r["composite"] = round(w["amount"] * r["rank_amount"] + w["hourly"] * r["rank_hourly"] + w["capital"] * r["rank_capital"], 2)
        else:
            r["composite"] = None
    rows.sort(key=lambda r: (r.get("composite") is None, -(r.get("composite") or 0), -(r.get("certainty") or 0)))
    return rows


async def category_history(store):
    """Finished = a handoff completed/rejected-after-approval or a position closed, whose outcome is known."""
    rows = await store.all("""SELECT o.id, o.source, o.data,
        (SELECT COALESCE(SUM(usd_micro),0) FROM income i WHERE i.opportunity_id=o.id) AS income,
        (SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) FROM costs c
           WHERE c.opportunity_id=o.id AND c.category!='capital_and_fee_reservation') AS cost,
        (SELECT COALESCE(SUM(minutes),0) FROM interventions v WHERE v.opportunity_id=o.id) AS minutes,
        (SELECT COUNT(*) FROM interventions v WHERE v.opportunity_id=o.id) AS touches,
        o.outcome
        FROM opportunities o WHERE o.outcome IS NOT NULL OR EXISTS(SELECT 1 FROM income i WHERE i.opportunity_id=o.id)""")
    out = {}
    for r in rows:
        cat = category(r)
        h = out.setdefault(cat, {"finished": 0, "paid": 0, "income_usd": 0.0, "cash_cost_usd": 0.0,
                                 "human_minutes": 0, "interventions": 0})
        if r["outcome"] in ("paid", "not_paid"):
            h["finished"] += 1
            h["paid"] += 1 if r["outcome"] == "paid" else 0
        h["income_usd"] += r["income"] / 1e6
        h["cash_cost_usd"] += r["cost"] / 1e6
        h["human_minutes"] += r["minutes"]
        h["interventions"] += r["touches"]
    return out


async def report(store, s):
    """Per-category strategy view: totals, win rate, realized net incl. time, and the current EV rule."""
    hist = await category_history(store)
    hourly = (s.get("human_hour_usd_micro") or 0) / 1e6
    counts = await store.all("SELECT source, data, status FROM opportunities")
    seen = {}
    for r in counts:
        c = category(r)
        seen.setdefault(c, {"discovered": 0, "in_progress": 0})
        seen[c]["discovered"] += 1
        if r["status"] in ("task_handoff_pending", "task_done_waiting_reward", "awaiting_approval"):
            seen[c]["in_progress"] += 1
    ai = await store.one("SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) AS n FROM costs WHERE category='ai'")
    pri = priors(s)
    rows = []
    for c, label in CATEGORIES.items():
        h = hist.get(c, {"finished": 0, "paid": 0, "income_usd": 0.0, "cash_cost_usd": 0.0, "human_minutes": 0, "interventions": 0})
        p, pay, w = calibrated(pri[c], h)
        time_cost = h["human_minutes"] * hourly / 60
        rows.append({"category": c, "label": label, **seen.get(c, {"discovered": 0, "in_progress": 0}), **h,
                     "win_rate": (h["paid"] / h["finished"]) if h["finished"] else None,
                     "time_cost_usd": round(time_cost, 2),
                     "net_after_time_usd": round(h["income_usd"] - h["cash_cost_usd"] - time_cost, 2),
                     "prior": pri[c], "current_p": p, "current_payout_usd": pay, "history_weight": round(w, 3)})
    return {"categories": rows, "shared_ai_cost_usd": ai["n"] / 1e6, "prior_weight": PRIOR_WEIGHT,
            "rule": "EV = 中奖概率 × 预期奖励 − 现金成本 − 人工分钟 × 时薪 − AI 成本；概率和奖励从可编辑的分类先验出发，按同类已完成结果逐步修正（约 10 个结果后以实际为主）。排序分 = EV × 分类权重；单个活动可手动置顶或跳过。"}
