"""Persistent notification outbox; dashboard always works, push channels are optional."""
import json
from common import Blocked, now
from config import binding
from network import get_json


def usd(v):
    return "未知" if v is None else "%.2f 美元"%(v/1_000_000)


def compose(row,dashboard=""):
    """Plain-text email. Contains official links and steps, never keys, tokens, signatures or balances."""
    kind=row["kind"]
    try: p=json.loads(row["payload"] or "{}")
    except ValueError: p={}
    tail="\n\n控制台："+(dashboard or "（未配置 DASHBOARD_URL）")+"\n事件编号："+row["id"][:64]+"\n本邮件不会要求你提供私钥、助记词或密码。"
    if kind=="task_handoff_approval_required":
        c=p.get("context",{})
        lines=["新的人工交接任务待你批准："+str(p.get("title",""))[:200],
               "官方链接："+str(p.get("url","")),
               "截止（Unix 秒）："+str(c.get("ends_at")),
               "奖励类型："+str(c.get("reward_kind"))+"（抽奖/积分/未公布空投不计收入）",
               "预计人工时间："+str(c.get("human_minutes"))+" 分钟；已知现金费用："+usd(c.get("known_cost_usd_micro"))+"；扣时间后净额："+usd(c.get("net_after_time_usd_micro")),
               "需要账户："+", ".join(c.get("required_accounts") or ["未知"])+"；需要公开发帖："+str(c.get("requires_public_post")),
               "","步骤（登录、验证码、发帖和最终提交由你本人完成）："]
        lines+=["%d. %s"%(i+1,str(x)[:300]) for i,x in enumerate(p.get("steps",[])[:15])]
        lines+=["","注意："]+["- "+str(w)[:200] for w in c.get("warnings",[])]
        lines+=["","先在控制台批准该交接单，再打开官方链接操作；完成后回控制台填写证据和实际用时。"]
        return "Auto Crypto 待批准任务："+str(p.get("title",""))[:60],"\n".join(lines)+tail
    if kind=="approval_required":
        sm=p.get("summary",{})
        lines=["链上资金方案待你批准（未批准不会执行）："+str(p.get("title",""))[:200],"来源："+str(p.get("url",""))]
        lines+=["%s：%s"%(k,v) for k,v in sm.items()]
        lines+=["","授权范围："]+["- "+json.dumps(x,ensure_ascii=False)[:300] for x in p.get("permissions",[])]
        lines+=["","批准必须在控制台输入独立批准密钥；邮件本身不能批准。"]
        return "Auto Crypto 资金方案待批准","\n".join(lines)+tail
    if kind=="periodic_report":
        r=p.get("realized",{})
        lines=["定期复盘（只统计已记录数据）：",
               "实际到账收入："+usd(r.get("income_usd_micro")),"全部费用（含 AI/API/托管）："+usd(r.get("costs_usd_micro")),
               "已实现净收益："+usd(r.get("realized_net_usd_micro")),
               "人工介入："+str(p.get("human_interventions"))+" 次，"+str(p.get("human_minutes"))+" 分钟",
               "活动漏斗："+json.dumps(p.get("funnel",[]),ensure_ascii=False)[:800],
               "模型用量："+json.dumps(p.get("model_usage",[]),ensure_ascii=False)[:800]]
        return "Auto Crypto 定期复盘","\n".join(lines)+tail
    if kind=="receiver_balance_increased":
        return "Auto Crypto 检测到钱包入账","实验钱包余额增加。请在控制台核对来源；如果是奖励，请登记到账记录。系统不会自动记为收入。"+tail
    return "Auto Crypto 需要处理："+kind,"Auto Crypto："+kind+"。请打开你的控制台查看。"+tail


async def deliver(env,store,limit=5):
    """Send up to `limit` pending events per wake-up; failures back off and stay visible."""
    result='idle'
    for _ in range(limit):
        result=await deliver_one(env,store)
        if result!='sent':
            break
    return result


async def deliver_one(env,store):
    token=str(binding(env,"TELEGRAM_BOT_TOKEN")); chat=str(binding(env,"TELEGRAM_CHAT_ID"))
    email_url=str(binding(env,"EMAIL_WEBHOOK_URL")); email_to=str(binding(env,"EMAIL_TO"))
    email_token=str(binding(env,"EMAIL_WEBHOOK_TOKEN")); email_api_key=str(binding(env,"EMAIL_API_KEY"))
    email_from=str(binding(env,"EMAIL_FROM"))
    email_ready=bool(email_to and ((email_url and email_token) or (email_api_key and email_from)))
    if not ((token and chat) or email_ready):
        return "dashboard_only"
    row=await store.one("SELECT * FROM events WHERE delivered_at IS NULL AND next_attempt<=? ORDER BY created_at LIMIT 1",now())
    if not row:
        return "idle"
    attempts=row["attempts"]+1
    await store.run("UPDATE events SET attempts=?,next_attempt=? WHERE id=?",attempts,now()+min(86400,60*2**min(attempts,10)),row["id"])
    # No address, balance, API token or transaction payload is included in the push message.
    subject,text=compose(row,str(binding(env,"DASHBOARD_URL")))
    try:
        if not email_ready:
            result=await get_json("https://api.telegram.org/bot"+token+"/sendMessage",method="POST",
                                  body={"chat_id":chat,"text":text,"disable_web_page_preview":True},
                                  headers={"Content-Type":"application/json"},timeout=8)
            if result.get("ok") is not True:
                raise Blocked("notification_failed")
        else:
            headers={"Content-Type":"application/json"}
            if email_api_key:
                headers["Authorization"]="Bearer "+email_api_key
                email_url=email_url or "https://api.resend.com/emails"
                body={"from":email_from,"to":[email_to],"subject":subject,"text":text}
            else:
                headers["Authorization"]="Bearer "+email_token
                body={"to":email_to,"subject":subject,"text":text}
            result=await get_json(email_url,method="POST",body=body,headers=headers,timeout=8)
            if result.get("ok") is False or result.get("success") is False:
                raise Blocked("notification_failed")
        await store.run("UPDATE events SET delivered_at=? WHERE id=?",now(),row["id"])
        return "sent"
    except Blocked:
        return "delivery_pending"  # At-least-once delivery; timeout can result in duplicate notifications.
