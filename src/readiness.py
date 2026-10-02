"""Deployment gate: report what is ready without exposing secrets or approving money."""
from common import Blocked
from config import binding, settings


async def check(env, store):
    checks = []
    def add(name, ok, detail): checks.append({"name": name, "ok": bool(ok), "detail": detail})
    control = await store.one("SELECT * FROM control WHERE id=1")
    add("database", control is not None, "D1 control row is present" if control else "apply migrations before starting")
    admin = str(binding(env, "ADMIN_TOKEN")); admin_ok = 32 <= len(admin) <= 256
    add("admin_token", admin_ok, "configured" if admin_ok else "missing or too short")
    try:
        s = settings(env); config_ok = True; config_detail = "valid"
    except Blocked as error:
        s = {}; config_ok = False; config_detail = str(error)
    add("settings", config_ok, config_detail)
    paused = bool(control and control["paused"])
    add("safe_start", paused, "paused; no new financial action" if paused else "not paused")
    ai_ok = bool(s.get("monthly_ai_usd_micro", 0) == 0 or s.get("provider_eligible") is True)
    add("ai_budget", ai_ok, "disabled or explicitly eligible" if ai_ok else "paid AI budget needs provider eligibility")
    executor_ok = getattr(env, "EXECUTOR", None) is not None
    add("executor_binding", executor_ok, "service binding present" if executor_ok else "not connected")
    email_ready = bool(
        binding(env, "EMAIL_TO") and
        ((binding(env, "EMAIL_WEBHOOK_URL") and binding(env, "EMAIL_WEBHOOK_TOKEN")) or
         (binding(env, "EMAIL_API_KEY") and binding(env, "EMAIL_FROM")))
    )
    notify = bool(binding(env, "TELEGRAM_BOT_TOKEN") and binding(env, "TELEGRAM_CHAT_ID")) or email_ready
    add("notification", notify, "configured" if notify else "dashboard only")
    adapter_ok = bool(s.get("vaults"))
    add("adapter_registry", adapter_ok, "reviewed adapter exists" if adapter_ok else "empty; research only")
    execution_secrets = all(bool(binding(env, name)) for name in ("EXECUTION_TOKEN",))
    add("execution_token", execution_secrets, "internal executor token present" if execution_secrets else "not configured")
    receiver_configured = bool(binding(env, "RECEIVER_ADDRESS") and binding(env, "RECEIVER_RPC_URL") and binding(env, "RECEIVER_CHAIN_ID"))
    add("receiver", receiver_configured, "read-only receiver configured" if receiver_configured else "wallet receiver not configured")
    add("loss_cap", s.get("max_loss_usd_micro", 0) > 0, "cumulative loss cap set (includes AI/API/hosting)" if s.get("max_loss_usd_micro", 0) > 0 else "max_loss_usd_micro is 0; nothing can be spent")
    add("profile", bool(s.get("participant_region")) and any((s.get("accounts") or {}).values()),
        "region and real single accounts declared" if s.get("participant_region") else "set participant_region and accounts so eligibility can be checked")
    add("human_time_value", s.get("human_hour_usd_micro") is not None,
        "manual time is priced" if s.get("human_hour_usd_micro") is not None else "human_hour_usd_micro unknown; fixed-reward tasks keep net unknown")
    blockers = [c["name"] for c in checks if not c["ok"]]
    research_blockers = {"database", "admin_token", "settings", "safe_start", "ai_budget"}
    return {"ready_for_research": not any(x in research_blockers for x in blockers),
            "ready_for_financial_execution": not blockers and adapter_ok,
            "paused": paused, "checks": checks, "blockers": blockers,
            "note": "Readiness never approves a proposal, enables cron, or unlocks a wallet."}
