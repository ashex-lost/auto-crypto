"""Build immutable, individually approved plans from operator-reviewed adapters."""
import json
from common import Blocked, address, canonical, decimal, digest, integer, now, campaign_timestamp
from finance import allocated_monthly_cost, estimate, worth_review


async def proposal(store,s,opportunity,analysis,preview_vault):
    if opportunity["source"] == "binance":
        raise Blocked("binance_launchpool_execution_not_verified")
    if opportunity["source"] != "merkl":
        raise Blocked("task_executor_not_connected")
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
    preview = await preview_vault({"vault_id":v["id"],"amount_raw":v["amount_raw"]})
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


SCREENING_VERSION = 'research-v2'
REASONS = {
    'source_stale': '资料超过一天未刷新，先更新再判断。',
    'campaign_not_live': '活动已结束或尚未开放。',
    'campaign_dates_unknown': '缺少可靠的活动截止时间。',
    'chain_unsupported': '当前执行器不支持这条链。',
    'borrowing_or_leverage': '包含借款或循环杠杆，超出当前策略。',
    'activity_type_unsupported': '当前执行器不支持这种参与方式。',
    'asset_review_needed': '需要先核查本金资产，币名本身不能证明资产真实。',
    'reward_conversion_needed': '奖励不是本金同币，当前缺少兑换适配。',
    'binance_execution_unverified': '尚未核实 Launchpool 官方自动参与接口。',
    'binance_terms_missing': '只有公告标题，不能据此确认活动期限和资格。',
    'adapter_review_needed': '尚未独立核查活动合约、条款和账户资格。',
    'eligible_for_analysis': '通过基础筛选，仍需分析、合约核查和你的批准。',
}


def prescreen(opportunity, timestamp=None):
    """No model/network/signing calls. A pass is permission to research, never to invest."""
    timestamp = now() if timestamp is None else timestamp
    data = json.loads(opportunity['data']) if isinstance(opportunity['data'], str) else opportunity['data']
    if opportunity['source']=='task':
        from tasks import assess_task
        result=assess_task(data,timestamp)
        observed=opportunity.get('observed_at',0)
        if type(observed) is not int or observed>timestamp+300 or timestamp-observed>86400:
            result['reasons'].append('source_stale')
            result['eligible_for_analysis']=False
        return {'version':SCREENING_VERSION,**result}
    reasons=[]
    observed=opportunity.get('observed_at',0)
    if type(observed) is not int or observed>timestamp+300 or timestamp-observed>86400:
        reasons.append('source_stale')
    if opportunity['source']=='binance':
        reasons.append('binance_execution_unverified')
        end=campaign_timestamp(data.get('earliestCampaignEnd'))
        if type(end) is int and end<=timestamp:
            reasons.append('campaign_not_live')
        if not data.get('article_text'):
            reasons.append('binance_terms_missing')
        return {'version':SCREENING_VERSION,'eligible_for_analysis':False,'reasons':reasons,
                'explanations':[REASONS[x] for x in reasons],'participation_approved':False}
    end=campaign_timestamp(data.get('earliestCampaignEnd'))
    if type(end) is not int or end<=0:
        reasons.append('campaign_dates_unknown')
    elif end<=timestamp or data.get('status')!='LIVE':
        reasons.append('campaign_not_live')
    start=campaign_timestamp(data.get('earliestCampaignStart'))
    if type(start) is int and start>timestamp:
        reasons.append('campaign_not_live')
    if data.get('chainId') not in (1,56):
        reasons.append('chain_unsupported')
    # Conservative textual filter; passing it does not prove absence of borrowing.
    import re
    text=' '.join(str(data.get(k) or '') for k in ('name','type','action','description','howToSteps')).lower()
    if re.search(r'borrow|leverag|looping|loop required|借款|杠杆|循环贷',text):
        reasons.append('borrowing_or_leverage')
    action=str(data.get('action') or '').lower().replace('_',' ')
    if action not in ('lend','deposit','supply'):
        reasons.append('activity_type_unsupported')
    tokens=data.get('tokens') or []
    if not isinstance(tokens,list): tokens=[]
    if not any(t.get('symbol') in ('USDC','USDT') for t in tokens if isinstance(t,dict)):
        reasons.append('asset_review_needed')
    rewards=data.get('rewards') or []
    stable_addresses={str(t.get('address') or '').lower() for t in tokens if isinstance(t,dict) and t.get('symbol') in ('USDC','USDT')}
    stable_addresses.discard('')
    if not isinstance(rewards,list) or not rewards or any(not isinstance(r,dict) or r.get('symbol') not in ('USDC','USDT') or str(r.get('address') or '').lower() not in stable_addresses for r in rewards):
        reasons.append('reward_conversion_needed')
    reasons=list(dict.fromkeys(reasons))
    return {'version':SCREENING_VERSION,'eligible_for_analysis':not reasons,
            'reasons':reasons or ['eligible_for_analysis'],
            'explanations':[REASONS[x] for x in reasons or ['eligible_for_analysis']],
            'participation_approved':False}
