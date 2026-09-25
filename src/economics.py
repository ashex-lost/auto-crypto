"""Deterministic cost scenarios. APR is a snapshot, never a promised reward."""
from decimal import Decimal, ROUND_CEILING
from common import Blocked, decimal, integer

COST_FIELDS = ("gas", "trading", "slippage", "bridge", "exit", "ai", "search_data", "hosting")


def estimate(principal_micro, apr_percent, days, costs, opportunity_cost_micro=0):
    integer(principal_micro, 1)
    integer(days, 1, 30)
    missing = [k for k in COST_FIELDS if costs.get(k) is None]
    for k in COST_FIELDS:
        if costs.get(k) is not None:
            integer(costs[k])
    integer(opportunity_cost_micro)
    rate = decimal(apr_percent)
    if not 0 <= rate <= 10000:
        raise Blocked("apr_out_of_range")
    base = int(Decimal(principal_micro)*rate/100*days/365)
    total = sum(v for k,v in costs.items() if k in COST_FIELDS and v is not None)
    return {
        "principal_usd_micro": principal_micro, "days": days,
        "apr_snapshot_percent": str(rate), "costs_usd_micro": costs,
        "total_known_cost_usd_micro": total, "missing_costs": missing,
        "opportunity_cost_usd_micro": opportunity_cost_micro,
        "reward_scenarios_usd_micro": {"zero":0,"conservative":base//4,"snapshot":base},
        "net_scenarios_usd_micro": {"zero":-total,"conservative":base//4-total,"snapshot":base-total} if not missing else None,
        "break_even_reward_usd_micro": total if not missing else None,
        "worst_loss_usd_micro": principal_micro+total,
        "assumptions": ["APR 是当前快照，奖励可能为零；25% 是压力情景，不是预测概率。",
                        "本金可能全部损失；机会成本另列，未从现金净收益重复扣除。",
                        "稳定币按一美元作情景计价，不代表保本；实际结算需保留价格证据。"],
    }


def allocated_monthly_cost(monthly_micro, days):
    return None if monthly_micro is None else int((Decimal(monthly_micro)*days/30).to_integral_value(rounding=ROUND_CEILING))


def worth_review(economics, minimum):
    return not economics["missing_costs"] and economics["net_scenarios_usd_micro"]["conservative"] >= minimum
