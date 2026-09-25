"""Report receipts and costs without counting returned principal as income."""
import json
from common import now


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
