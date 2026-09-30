"""Task research gate. No account access, social posting, signing, or submissions."""
from common import campaign_timestamp, now, integer


def assess_task(data, timestamp=None):
    timestamp=now() if timestamp is None else timestamp
    reasons=[]
    if data.get('adapter') == 'galxe_read_v1':
        from galxe import availability
        reasons.extend(availability(data.get('official', {}), timestamp))
    end=campaign_timestamp(data.get('ends_at'))
    if end is None: reasons.append('deadline_unknown')
    elif end<=timestamp: reasons.append('task_ended')
    if data.get('automation')!='allowed': reasons.append('automation_not_verified')
    if data.get('eligibility')!='confirmed': reasons.append('eligibility_not_verified')
    if data.get('requires_trading') is not False: reasons.append('trading_requirement_or_unknown')
    if data.get('requires_deposit') is not False: reasons.append('deposit_requirement_or_unknown')
    if data.get('requires_public_post') is not False: reasons.append('public_post_needs_separate_approval')
    reward=data.get('reward_kind')
    if reward not in ('fixed','raffle','points','unannounced'): reasons.append('reward_terms_unknown')
    costs=data.get('costs_usd_micro',{})
    required=('gas','trading','claim','ai','hosting','other')
    missing=[k for k in required if costs.get(k) is None]
    total=sum(integer(costs[k]) for k in required if costs.get(k) is not None)
    minutes=data.get('human_minutes')
    if minutes is not None:integer(minutes)
    # Pools, points and hypothetical airdrops are never participant income.
    fixed=data.get('reward_per_person_usd_micro') if reward=='fixed' else None
    if fixed is not None:integer(fixed)
    net=fixed-total if fixed is not None and not missing else None
    # Unknown terms can be researched but never used to authorize participation.
    research_ok = not reasons
    if data.get('adapter') == 'galxe_read_v1':
        research_ok = not availability(data.get('official', {}), timestamp) and data.get('reward_kind') != 'points'
    return {'execution_blockers': reasons + (['task_executor_not_connected'] if data.get('adapter') == 'galxe_read_v1' else []), 'kind':'task_research' ,'reasons':reasons,'missing_costs':missing,
            'known_cost_usd_micro':total,'human_minutes':minutes,
            'conditional_net_usd_micro':net,'reward_kind':reward,
            'payout_probability':None,'participation_approved':False,
            'execution_supported':False,'eligible_for_analysis':research_ok,
            'note':'Research only. Fixed payout remains conditional on eligibility, availability and verification; no task executor is connected.'}
