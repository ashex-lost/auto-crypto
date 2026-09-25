"""Build immutable, individually approved plans from operator-reviewed adapters."""
import json
from common import Blocked, address, canonical, decimal, digest, integer, now
from economics import allocated_monthly_cost, estimate, worth_review
from execution import executor


async def proposal(env,store,s,opportunity,analysis):
    if opportunity["source"] == "binance":
        raise Blocked("binance_launchpool_execution_not_verified")
    data = json.loads(opportunity["data"])
    if data.get("status")!="LIVE" or int(data.get("earliestCampaignEnd") or 0)<=now():
        raise Blocked("campaign_not_live")
    if analysis["recommendation"] == "reject" or analysis["borrowing_required"]:
        raise Blocked("activity_rejected")
    if analysis["automation"]=="prohibited" or analysis["eligibility"]=="not_eligible":
        raise Blocked("activity_not_permitted")
    matches = [v for v in s["vaults"] if str(v.get("opportunity_id"))==str(data["id"])]
    if len(matches)!=1:
        raise Blocked("activity_adapter_review_needed")
    v = matches[0]
    if v.get("eligibility_reviewed") is not True or v.get("automation_allowed") is not True or not v.get("terms_evidence_url"):
        raise Blocked("activity_terms_review_needed")
    if address(data["explorerAddress"])!=address(v["vault"]) or data["chainId"]!=v["chain_id"]:
        raise Blocked("activity_contract_changed")
    rewards = data.get("rewards",[])
    if not rewards or any(address(r["address"])!=address(v["asset"]) for r in rewards):
        raise Blocked("non_underlying_reward_not_supported")
    principal = integer(v["principal_usd_micro"],1,s["max_principal_usd_micro"])
    days = min(s["horizon_days"], (int(data["earliestCampaignEnd"])-now())//86400)
    if days<1:
        raise Blocked("campaign_window_too_short")
    preview = await executor(env,"/preview",{"vault_id":v["id"],"amount_raw":v["amount_raw"]})
    if not preview.get("ready"):
        raise Blocked("wallet_not_ready")
    nominal=(int(v['amount_raw'])*1000000+10**preview['asset_decimals']-1)//10**preview['asset_decimals']
    if principal<nominal:
        raise Blocked('principal_unit_mismatch')
    # Provider/host/bridge costs are explicit reviewed estimates, never default zero.
    friction = v.get("costs_usd_micro",{})
    costs = {"gas":preview.get("max_gas_usd_micro"),"trading":friction.get("trading"),
             "slippage":friction.get("slippage"),"bridge":friction.get("bridge"),"exit":friction.get("exit"),
             "ai":max(analysis["analysis_cost_usd_micro"]*3,allocated_monthly_cost(s['monthly_ai_usd_micro'],days),friction.get("ai",0)),
             "search_data":s["data_search_usd_micro_per_cycle"],
             "hosting":allocated_monthly_cost(s["monthly_fixed_usd_micro"],days)}
    economics = estimate(principal,data["apr"],days,costs,friction.get("opportunity_cost",0))
    if not worth_review(economics,s["min_net_usd_micro"]):
        raise Blocked("net_return_below_threshold_or_cost_unknown")
    spent = await store.one("SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) AS total FROM costs")
    if economics["worst_loss_usd_micro"]+spent["total"]>s["max_loss_usd_micro"]:
        raise Blocked("loss_budget_exhausted")
    # A single active plan avoids overlapping capital and accidental reward attribution.
    active = await store.one("SELECT id FROM proposals WHERE state IN ('pending_approval','approval_submitting','approved','executing','holding','needs_attention') LIMIT 1")
    if active:
        raise Blocked("one_active_plan_limit")
    t = now()
    plan = {"version":1,"adapter":"erc4626_merkl_v1","vault_id":v["id"],
            "opportunity_id":opportunity["id"],"evidence_hash":opportunity["fingerprint"],
            "chain_id":v["chain_id"],"wallet":preview["wallet"],"asset":address(v["asset"]),
            "vault":address(v["vault"]),"distributor":preview["distributor"],
            "amount_raw":str(v["amount_raw"]),"shares_raw":preview["shares_raw"],
            "max_fee_wei":preview["max_fee_wei"],"gas_limit":preview["gas_limit"],
            "max_gas_price_wei":preview["max_gas_price_wei"],
            "created_at":t,"expires_at":t+1800,"exit_at":t+days*86400,
            "claim_until":t+(days+7)*86400,"max_claims":2,"max_txs":7,
            "min_claim_raw":str(v["min_claim_raw"]),"stop_loss_bps":integer(v["stop_loss_bps"],1,5000)}
    hash_value = digest(plan)
    return {"id":hash_value,"plan":plan,"digest":hash_value,"economics":economics,"analysis":analysis,
            "simulation":preview,"terms_evidence_url":v["terms_evidence_url"],
            "caveats":["仅支持一个经过核查的 ERC4626 金库及同种稳定币奖励；不支持借贷、跨链或任意兑换。",
                       "模拟是当前链状态的预检查，不保证未来成功；退出限价无法由标准 redeem 参数在链上锁定。",
                       "止损会触发退出尝试；合约故障、流动性或价格突变可能使损失超过阈值。"]}
