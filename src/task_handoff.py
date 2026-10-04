"""Human handoff for permitted task activities; no browser, login or CAPTCHA automation."""
from common import Blocked, canonical, digest, now

# Official page lists the actual tasks; these steps never include bypassing checks or extra accounts.
GENERIC_STEPS=["打开官方活动页面，核对活动方、截止时间和奖励规则与控制台一致。",
               "只用你本人唯一的账户登录；需要连接钱包时只连接独立实验钱包，并逐项阅读签名内容。",
               "按页面列出的任务逐项完成；验证码、身份验证、发帖和最终提交都由你本人完成。",
               "任何要求无限授权、转账、私钥或助记词的步骤都立即停止，并在控制台标记异常。",
               "完成后回到控制台填写完成证据和实际用时；奖励到账后再登记到账记录。"]
CONTEXT_KEYS=("ends_at","reward_kind","requires_public_post","required_accounts","human_minutes",
              "net_after_time_usd_micro","known_cost_usd_micro","eligibility","qualification","ai_estimated_fields","warnings","fingerprint_hint","ev")


def prepare(data, timestamp=None, context=None):
    timestamp=now() if timestamp is None else timestamp
    url=str(data.get("url") or data.get("official_url") or "")
    if not url.startswith("https://") or len(url)>2048:
        raise Blocked("task_url_invalid")
    title=str(data.get("title") or data.get("name") or "task")[:240]
    raw_steps=data.get("steps") or data.get("howToSteps") or []
    if isinstance(raw_steps,str): raw_steps=[raw_steps]
    if not isinstance(raw_steps,list) or not raw_steps or len(raw_steps)>30:
        raise Blocked("task_steps_missing")
    steps=[str(step)[:500] for step in raw_steps]
    context={k:v for k,v in (context or {}).items() if k in CONTEXT_KEYS}
    if len(canonical(context))>8000:
        raise Blocked("task_context_too_large")
    plan={"version":2,"mode":"manual_handoff","title":title,"url":url,"steps":steps,
          "requires_login":True,"requires_user_confirmation":True,"created_at":timestamp,
          "context":context,
          "note":"只提供官方页面和步骤；登录、验证码、发布和最终提交由用户在页面内完成。"}
    return {"id":digest(plan),"digest":digest(plan),"plan":plan}


def evidence(text):
    if not isinstance(text,str) or not 1<=len(text)<=4000:
        raise Blocked("task_evidence_invalid")
    return text
