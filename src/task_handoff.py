"""Human handoff for permitted task activities; no browser, login or CAPTCHA automation."""
from common import Blocked, canonical, digest, now


def prepare(data, timestamp=None):
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
    plan={"version":1,"mode":"manual_handoff","title":title,"url":url,"steps":steps,
          "requires_login":True,"requires_user_confirmation":True,"created_at":timestamp,
          "note":"只提供官方页面和步骤；登录、验证码、发布和最终提交由用户在页面内完成。"}
    return {"id":digest(plan),"digest":digest(plan),"plan":plan}


def evidence(text):
    if not isinstance(text,str) or not 1<=len(text)<=4000:
        raise Blocked("task_evidence_invalid")
    return text
