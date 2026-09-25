"""All money rules: estimates, actual receipts, valuation and financial reports.

No AI, wallet, environment bindings or network client is imported here.
The caller supplies the persistence interface and quote reader when needed.
Estimates, confirmed quantities and market valuations remain distinct fields.
"""
import json
from decimal import Decimal, ROUND_CEILING
from common import Blocked, decimal, integer, now


# Before participation: costs and reward scenarios.
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


# Provider usage is a cost calculation, independent of the model client.
def usage_cost(usage, s):
    i = integer(usage.get("input_tokens"),0,100000)
    o = integer(usage.get("output_tokens"),0,10000)
    # Charge all input at the uncached rate, a conservative estimate until billing reconciliation.
    return (i*s["input_usd_micro_per_million"]+o*s["output_usd_micro_per_million"]+999999)//1000000


# After participation: confirmed receipts and accounting.
def position_result(state):
    deposited=int(state.get("deposited_raw","0"))
    returned=int(state.get("redeemed_raw","0"))
    rewards=int(state.get("claimed_raw","0"))
    closed=state.get("stage") in ("exited","closed")
    return {"asset":state["plan"]["asset"],"chain_id":state["plan"]["chain_id"],
            "principal_deposited_raw":str(deposited),"principal_and_yield_returned_raw":str(returned),
            "reward_received_raw":str(rewards),"gas_paid_wei":state.get("fee_wei","0"),
            "realized_asset_pnl_before_costs_raw":str(returned-deposited+rewards) if closed else str(rewards),
            "open_position_cost_basis_raw":"0" if closed else str(deposited),
            "unclaimed_rewards_in_realized_pnl":False,
            "net_usd_micro":None,
            "valuation_status":"requires_fee_and_asset_price_reconciliation",
            "market_valuation":state.get('valuation',{'status':'not_valued'}),
            "receipts":state.get("receipts",[])}


async def summary(store):
    costs=await store.all("SELECT category,SUM(COALESCE(actual_micro,reserved_micro)) AS accounted_micro,SUM(CASE WHEN state!='confirmed' THEN reserved_micro ELSE 0 END) AS uncertain_or_reserved_micro FROM costs WHERE category!='capital_and_fee_reservation' GROUP BY category")
    reserves=await store.all("SELECT proposal_id,reserved_micro,evidence FROM costs WHERE category='capital_and_fee_reservation'")
    plans=await store.all("SELECT id,state,executor_state FROM proposals WHERE executor_state IS NOT NULL ORDER BY created_at DESC LIMIT 50")
    positions=[{"id":p["id"],"state":p["state"],**position_result(json.loads(p["executor_state"]))} for p in plans]
    complete=bool(positions) and all(p['state']=='closed' and p['market_valuation']['status']=='market_estimate' for p in positions)
    total_count=await store.one("SELECT COUNT(*) AS n FROM proposals WHERE executor_state IS NOT NULL")
    estimate=None
    if complete and total_count['n']<=50:
        estimate=sum(p['market_valuation']['net_before_shared_operating_costs_usdt_micro'] for p in positions)-sum(c['accounted_micro'] for c in costs)
    return {"as_of":now(),"costs":costs,"risk_reservations_not_expenses":reserves,"positions":positions,
             "net_usd_micro":None,"net_usdt_micro_estimate":estimate,
             "note":"链上数量由回执确认。市场估值使用记录时现货价，运行费按美元≈USDT估算；未结算仓位、未兑现奖励不算已实现利润。固定费及不确定账单保守按预留额扣除，最终美元净收益仍待账单核对。"}


async def reconcile_reservation(store,proposal,state):
    """Release recovered principal only; keep conservative fee/loss reserves, not fake expenses."""
    if state['stage']!='closed':
        return
    details=json.loads(proposal['plan']);economics=details['economics']
    capital=economics['principal_usd_micro'];maximum=int(details['plan']['amount_raw'])
    deposited=int(state['deposited_raw']);returned=int(state['redeemed_raw'])
    token_loss=max(0,deposited-returned)
    loss_reserve=(capital*token_loss+maximum-1)//maximum
    fee_reserve=economics['total_known_cost_usd_micro']
    await store.run("UPDATE costs SET reserved_micro=?,evidence=? WHERE id=? AND state='reserved'",
                    loss_reserve+fee_reserve,json.dumps({'basis':'capital_recovery_receipts_and_conservative_fee_reserve',
                    'token_loss_raw':str(token_loss),'fees_not_finally_valued':True}),"position:"+proposal['id'])


# Mark confirmed amounts to market; this does not invent a sale.
def value_receipts(state,decimals,asset_price,native_price,timestamp):
    asset_price=decimal(asset_price);native_price=decimal(native_price)
    if asset_price<=0 or native_price<=0 or not 0<=decimals<=18:
        raise Blocked('invalid_market_quote')
    closed=state['stage'] in ('exited','closed')
    raw=int(state.get('claimed_raw','0'))
    if closed:
        raw+=int(state.get('redeemed_raw','0'))-int(state.get('deposited_raw','0'))
    gross=int(Decimal(raw)*asset_price*1000000/(10**decimals))
    gas=int((Decimal(state.get('fee_wei','0'))*native_price/Decimal(10**12)).to_integral_value(rounding=ROUND_CEILING))
    return {'status':'market_estimate','as_of':timestamp,'quote_currency':'USDT',
            'asset_price_usdt':str(asset_price),'native_price_usdt':str(native_price),
            'realized_asset_pnl_valued_usdt_micro':gross,'gas_valued_usdt_micro':gas,
            'net_before_shared_operating_costs_usdt_micro':gross-gas,
            'open_principal_excluded':not closed,
            'basis':'current_spot_mark_of_verified_receipts_not_actual_sale_proceeds'}


async def value_position(state,s,read_quote):
    matches=[v for v in s['vaults'] if v['id']==state['plan']['vault_id']]
    if len(matches)!=1:
        return {'status':'adapter_not_configured'}
    v=matches[0];symbol=v.get('asset_symbol');decimals=v.get('asset_decimals')
    if symbol not in ('USDC','USDT') or type(decimals) is not int:
        return {'status':'asset_quote_not_configured'}
    native={1:'ETHUSDT',56:'BNBUSDT'}.get(state['plan']['chain_id'])
    if not native:
        return {'status':'native_quote_not_configured'}
    try:
        root='https://data-api.binance.vision/api/v3/ticker/price?symbol='
        native_data=await read_quote(root+native,timeout=8,max_bytes=2048)
        if native_data.get('symbol')!=native:
            raise Blocked('market_symbol_mismatch')
        asset_price='1'
        if symbol!='USDT':
            asset_data=await read_quote(root+symbol+'USDT',timeout=8,max_bytes=2048)
            if asset_data.get('symbol')!=symbol+'USDT':
                raise Blocked('market_symbol_mismatch')
            asset_price=asset_data['price']
        return value_receipts(state,decimals,asset_price,native_data['price'],now())
    except (Blocked,KeyError,ValueError):
        return {'status':'market_quote_unavailable','as_of':now()}
