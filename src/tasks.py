"""Task research gate. No account access, social posting, signing, or submissions.

Two separate outputs:
- eligible_for_analysis: may this task be sent to paid AI research?
- handoff_blockers: what still prevents a manual handoff (you do login/CAPTCHA/submit yourself).
Pools, points and unannounced airdrops never become income estimates.
"""
from common import campaign_timestamp, now, integer

COST_KEYS=('gas','trading','claim','ai','hosting','other')
# Reasons a human handoff can resolve (the human does the steps, after approving them).
HANDOFF_RESOLVABLE={'automation_not_verified','eligibility_not_verified','public_post_needs_separate_approval'}


def time_cost(minutes, hour_value):
    """Manual minutes valued at your stated hourly rate. Unknown rate with real minutes stays unknown."""
    if minutes is None:
        return None
    integer(minutes,0,100000)
    if minutes==0:
        return 0
    if hour_value is None:
        return None
    return (minutes*integer(hour_value)+59)//60


def assess_task(data, timestamp=None, s=None):
    timestamp=now() if timestamp is None else timestamp
    s=s or {}
    reasons=[]
    if data.get('adapter') == 'galxe_read_v1':
        from galxe import availability
        reasons.extend(availability(data.get('official', {}), timestamp))
    end=campaign_timestamp(data.get('ends_at'))
    if end is None: reasons.append('deadline_unknown')
    elif end<=timestamp: reasons.append('task_ended')
    # Checks run every 8 hours and you need time to act: less than 12 hours left is not actionable.
    elif end-timestamp<12*3600: reasons.append('deadline_too_close')
    if data.get('automation')!='allowed': reasons.append('automation_not_verified')
    if data.get('eligibility')!='confirmed': reasons.append('eligibility_not_verified')
    if data.get('requires_trading') is not False: reasons.append('trading_requirement_or_unknown')
    if data.get('requires_deposit') is not False: reasons.append('deposit_requirement_or_unknown')
    if data.get('requires_public_post') is not False: reasons.append('public_post_needs_separate_approval')
    accounts=s.get('accounts') or {}
    required=data.get('requires_accounts')
    if isinstance(required,list) and accounts:
        missing_accounts=[a for a in required if not accounts.get(a)]
        if missing_accounts: reasons.append('account_not_available')
    else:
        missing_accounts=None
    reward=data.get('reward_kind')
    if reward not in ('fixed','raffle','points','unannounced'): reasons.append('reward_terms_unknown')
    costs=data.get('costs_usd_micro',{})
    missing=[k for k in COST_KEYS if costs.get(k) is None]
    total=sum(integer(costs[k]) for k in COST_KEYS if costs.get(k) is not None)
    minutes=data.get('human_minutes')
    labour=time_cost(minutes,s.get('human_hour_usd_micro'))
    # Pools, points and hypothetical airdrops are never participant income.
    fixed=data.get('reward_per_person_usd_micro') if reward=='fixed' else None
    if fixed is not None:integer(fixed)
    net=fixed-total if fixed is not None and not missing else None
    net_after_time=net-labour if net is not None and labour is not None else None
    # Unknown terms can be researched but never used to authorize participation.
    research_ok = not reasons
    if data.get('adapter') == 'galxe_read_v1':
        research_ok = not availability(data.get('official', {}), timestamp) and data.get('reward_kind') != 'points'
    handoff_blockers=[r for r in reasons if r not in HANDOFF_RESOLVABLE]
    if missing: handoff_blockers.append('cash_cost_unknown')
    if fixed is not None:
        if net_after_time is None: handoff_blockers.append('net_after_time_unknown')
        elif net_after_time<s.get('min_net_usd_micro',1_000_000): handoff_blockers.append('net_below_threshold')
    else:
        # No cash value can be estimated. Only allowed as an explicit, small, zero-cash-cost experiment.
        cap=s.get('speculative_task_max_minutes',0)
        if not (cap and total==0 and not missing and minutes is not None and minutes<=cap):
            handoff_blockers.append('reward_value_unknown_research_only')
    return {'execution_blockers': reasons + (['task_executor_not_connected'] if data.get('adapter') == 'galxe_read_v1' else []),
            'kind':'task_research','reasons':reasons,'missing_costs':missing,
            'known_cost_usd_micro':total,'human_minutes':minutes,'human_time_cost_usd_micro':labour,
            'missing_accounts':missing_accounts,
            'conditional_net_usd_micro':net,'net_after_time_usd_micro':net_after_time,'reward_kind':reward,
            'payout_probability':None,'participation_approved':False,
            'handoff_blockers':list(dict.fromkeys(handoff_blockers)),
            'execution_supported':False,'eligible_for_analysis':research_ok,
            'note':'Research only. Fixed payout remains conditional on eligibility, availability and verification; no task executor is connected. Human time is valued at your stated hourly rate.'}
