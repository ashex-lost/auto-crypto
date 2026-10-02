"""Read bindings, never local environment files. Missing budgets disable paid work."""
import json
from common import Blocked, integer


ACCOUNT_KINDS=("binance","x","discord","telegram","evm_wallet","email","github")


def binding(env, name, default=""):
    value = getattr(env, name, None)
    return default if value is None else value


def settings(env):
    raw = binding(env, "SETTINGS_JSON", "{}")
    try:
        s = json.loads(str(raw))
    except (ValueError, TypeError):
        raise Blocked("settings_invalid") from None
    defaults = {
        "monthly_ai_usd_micro": 0,
        "lifetime_cost_usd_micro": 0,
        "monthly_fixed_usd_micro": None,
        "data_search_usd_micro_per_cycle": None,
        "max_principal_usd_micro": 0,
        "max_loss_usd_micro": 0,
        "min_net_usd_micro": 1_000_000,
        "horizon_days": 7,
        "discovery_seconds": 3600,
        "ai_calls_per_day": 3,
        "provider_eligible": False,
        "participant_region": "",
        "model": "gpt-6-luna",
        "input_usd_micro_per_million": 100_000,
        "output_usd_micro_per_million": 500_000,
        "vaults": [],
        "review_model": "gpt-6-sol",
        "review_input_usd_micro_per_million": 2_000_000,
        "review_output_usd_micro_per_million": 10_000_000,
        "analysis_max_call_usd_micro": 50_000,
        "review_max_call_usd_micro": 200_000,
        "research_principal_usd_micro": 100_000_000,
        "review_enabled": False,
        # Value of one hour of your manual time; None = unknown, so task net stays unknown.
        "human_hour_usd_micro": None,
        # Your real single accounts; requirements for an unavailable account block a task.
        "accounts": {},
        # Conservative net / worst loss, in basis points. 0 = shown but not enforced.
        "min_reward_to_risk_bps": 0,
        "report_days": 7,
        # Raffles/points/unannounced rewards have no cash estimate. >0 allows a manual handoff only when
        # cash cost is known to be zero and the estimated manual time is at most this many minutes.
        "speculative_task_max_minutes": 0,
        # "workers_ai" uses the Cloudflare AI binding (no external key); "openai" uses MODEL_API_KEY.
        "provider": "openai",
    }
    if not isinstance(s, dict) or set(s) - set(defaults):
        raise Blocked("settings_unknown_field")
    defaults.update(s)
    for k, v in defaults.items():
        if k.endswith("usd_micro") or k.endswith("per_million"):
            if v is not None:
                integer(v)
    integer(defaults["horizon_days"], 1, 30)
    integer(defaults["discovery_seconds"], 900, 86400)
    integer(defaults["ai_calls_per_day"], 0, 20)
    if type(defaults["provider_eligible"]) is not bool or not isinstance(defaults["vaults"], list):
        raise Blocked("settings_invalid")
    for key in ('review_enabled',):
        if type(defaults[key]) is not bool:
            raise Blocked('settings_invalid')
    if defaults['provider'] not in ('openai','workers_ai'):
        raise Blocked('model_config_invalid')
    for key in ('model','review_model'):
        if not isinstance(defaults[key],str) or not 1<=len(defaults[key])<=100:
            raise Blocked('model_config_invalid')
    integer(defaults['research_principal_usd_micro'],1)
    integer(defaults['min_reward_to_risk_bps'],0,1_000_000)
    integer(defaults['report_days'],1,31)
    integer(defaults['speculative_task_max_minutes'],0,120)
    accounts=defaults['accounts']
    if not isinstance(accounts,dict) or set(accounts)-set(ACCOUNT_KINDS) or any(type(v) is not bool for v in accounts.values()):
        raise Blocked('accounts_invalid')
    defaults['accounts']={k:accounts.get(k,False) for k in ACCOUNT_KINDS}
    if len(defaults["vaults"]) > 10:
        raise Blocked("too_many_vaults")
    return defaults
