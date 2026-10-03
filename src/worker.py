"""Cloudflare Python entry point: authenticated dashboard/API and scheduled events."""
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit
from workers import WorkerEntrypoint, Response
from common import Blocked, canonical, json_object, now, digest
from config import binding, settings
from storage import Store
from engine import tick
from execution import approve,executor
from finance import summary, metrics, income_entry, cost_entry
from dashboard import PAGE
from readiness import check as readiness_check
from task_handoff import evidence
from galxe import capabilities, check_eligibility

CRON_STEPS=12
HEADERS={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer"}


def auth(header,secret):
    if not isinstance(secret,str) or not 32<=len(secret)<=256 or not isinstance(header,str) or len(header)>300:
        return False
    return hmac.compare_digest(hashlib.sha256(header.encode()).digest(),hashlib.sha256(("Bearer "+secret).encode()).digest())


async def intervened(store,kind,target=None,opportunity_id=None,minutes=None):
    """Every human action is counted so reviews can measure how much automation actually saves."""
    await store.run("INSERT INTO interventions(at,kind,target,opportunity_id,minutes) VALUES(?,?,?,?,?)",
                    now(),kind,target,opportunity_id,minutes)


def response(data,status=200):
    return Response.from_json(data,status=status,headers=HEADERS)


class Default(WorkerEntrypoint):
    async def fetch(self,request):
        path=urlsplit(request.url).path
        if path=="/" and request.method=="GET":
            return Response(PAGE,headers={**HEADERS,"Content-Type":"text/html; charset=utf-8",
                "Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
        if path=="/healthz":
            return response({"service":"auto-crypto","process_alive":True,"financial_readiness":"check_authenticated_status"})
        if not auth(request.headers.get("Authorization"),str(binding(self.env,"ADMIN_TOKEN"))):
            return response({"error":"unauthorized"},401)
        try:
            store=Store(self.env.DB)
            if request.method=="GET" and path=="/api/status":
                from config import load_settings
                s=await load_settings(self.env,store);control=await store.one("SELECT * FROM control WHERE id=1")
                if not control:
                    raise Blocked("database_not_initialized")
                proposals=await store.all("SELECT * FROM proposals ORDER BY created_at DESC LIMIT 20")
                candidates=await store.all("SELECT id,title,url,observed_at,status,analysis,screening FROM opportunities ORDER BY observed_at DESC LIMIT 50")
                for c in candidates:
                    c["analysis"]=json.loads(c["analysis"]) if c["analysis"] else None
                    c["screening"]=json.loads(c["screening"]) if c["screening"] else None
                return response({"runtime":{"paused":bool(control["paused"]),"last_tick":control["last_tick"],
                    "last_success":control["last_success"],"last_cron":control["last_cron"],"error":control["error_code"],
                    "sources":await store.all("SELECT * FROM sources"),"model_key_connected":bool(binding(self.env,"MODEL_API_KEY")),
                    "model_access_confirmed":s["provider_eligible"],"reviewed_adapters":len(s["vaults"]),
                    "notification_channel":"telegram" if binding(self.env,"TELEGRAM_BOT_TOKEN") and binding(self.env,"TELEGRAM_CHAT_ID") else ("email" if binding(self.env,"EMAIL_TO") and ((binding(self.env,"EMAIL_WEBHOOK_URL") and binding(self.env,"EMAIL_WEBHOOK_TOKEN")) or (binding(self.env,"EMAIL_API_KEY") and binding(self.env,"EMAIL_FROM"))) else "dashboard_only")},
                    "proposals":[{"id":p["id"],"state":p["state"],"digest":p["digest"],"details":json.loads(p["plan"]),"error":p["error_code"]} for p in proposals],
                    "opportunities":candidates,"ledger":await summary(store),
                    "model_runs":await store.all("SELECT id,role,model,prompt_version,created_at,state,reserved_micro,actual_micro,error_code FROM model_runs ORDER BY created_at DESC LIMIT 20"),
                    "events":await store.all("SELECT id,kind,created_at,delivered_at,payload FROM events ORDER BY created_at DESC LIMIT 20"),
                    "reviews":[json.loads(r["data"]) for r in await store.all("SELECT data FROM reviews ORDER BY created_at DESC LIMIT 5")]})
            if request.method=="GET" and path=="/api/adapters":
                return response({"adapters":[capabilities(self.env)],
                    "task_checks":await store.all("SELECT opportunity_id,checked_at,status,result FROM task_checks ORDER BY checked_at DESC LIMIT 20")})
            if request.method=="GET" and path=="/api/receiver":
                rows=await store.all("SELECT observed_at,status,chain_id,address,native_raw,assets,error_code FROM receiver_snapshots ORDER BY observed_at DESC LIMIT 20")
                for row in rows:
                    if row.get("assets"):
                        row["assets"]=json.loads(row["assets"])
                return response({"configured":bool(binding(self.env,"RECEIVER_ADDRESS") and binding(self.env,"RECEIVER_RPC_URL") and binding(self.env,"RECEIVER_CHAIN_ID")),
                                 "address":binding(self.env,"RECEIVER_ADDRESS") or None,"chain_id":binding(self.env,"RECEIVER_CHAIN_ID") or None,
                                 "snapshots":rows})
            if request.method=="GET" and path=="/api/task-handoffs":
                rows=await store.all("SELECT id,opportunity_id,digest,plan,state,created_at,approved_at,completed_at,evidence FROM task_handoffs ORDER BY created_at DESC LIMIT 30")
                for row in rows:
                    row["plan"]=json.loads(row["plan"])
                return response({"handoffs":rows})
            if request.method=="GET" and path=="/api/strategy":
                from config import load_settings
                from strategy import report, category
                s=await load_settings(self.env,store)
                rows=await store.all("SELECT id,source,title,url,status,data,ev,priority,skipped,outcome,observed_at FROM opportunities ORDER BY skipped, priority DESC, observed_at DESC LIMIT 300")
                ranking=[]
                for r in rows:
                    ev=json.loads(r["ev"]) if r["ev"] else None
                    ranking.append({"id":r["id"],"title":r["title"],"url":r["url"],"status":r["status"],"category":category(r),
                                    "priority":r["priority"],"skipped":bool(r["skipped"]),"outcome":r["outcome"],
                                    "ev_usd":ev and ev.get("ev_usd"),"score":ev and ev.get("score"),
                                    "p_paid":ev and ev.get("p_paid"),"payout_usd":ev and ev.get("payout_usd"),"basis":ev and ev.get("basis")})
                ranking.sort(key=lambda x:(x["skipped"],-x["priority"],-(x["score"] if x["score"] is not None else -1e9)))
                blocked=await store.all("SELECT key,reason,example_id,at FROM ineligible_keys ORDER BY at DESC")
                return response({**(await report(store,s)),"ranking":ranking[:100],"ineligible_projects":blocked})
            if request.method=="GET" and path=="/api/settings":
                from config import load_settings, OVERRIDABLE
                row=await store.one("SELECT data,updated_at FROM settings_overrides WHERE id=1")
                s=await load_settings(self.env,store)
                return response({"overrides":json.loads(row["data"]) if row else {},"updated_at":row and row["updated_at"],
                                 "effective":{k:s.get(k) for k in OVERRIDABLE},"editable_fields":list(OVERRIDABLE)})
            if request.method=="GET" and path=="/api/metrics":
                return response(await metrics(store))
            if request.method=="GET" and path=="/api/readiness":
                return response(await readiness_check(self.env, store))
            if request.method!="POST":
                return response({"error":"not_found"},404)
            if request.headers.get("Content-Type","").split(";")[0]!="application/json":
                raise Blocked("json_required")
            # Cross-origin browsers cannot mutate state; authorization is never a cookie.
            origin=request.headers.get("Origin")
            if origin and origin != urlsplit(request.url).scheme+"://"+urlsplit(request.url).netloc:
                return response({"error":"origin_rejected"},403)
            body=json_object(await request.text(),16384)
            if path=="/api/adapters/galxe/check":
                if set(body)!={"opportunity_id"} or not isinstance(body["opportunity_id"],str) or len(body["opportunity_id"])>110:
                    raise Blocked("galxe_invalid_id")
                return response(await check_eligibility(self.env,store,body["opportunity_id"]))
            if path=="/api/settings":
                from config import settings as check_settings
                if not isinstance(body.get("overrides"),dict) or set(body)!={"overrides"}:
                    raise Blocked("invalid_settings_update")
                check_settings(self.env,body["overrides"])  # validates every field before saving
                await store.run("INSERT INTO settings_overrides(id,data,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                                canonical(body["overrides"]),now())
                await store.audit("settings_override","settings",digest(body["overrides"]))
                return response({"saved":True})
            m=re.fullmatch(r"/api/activities/([A-Za-z0-9:_-]{1,120})",path)
            if m:
                key=m.group(1); row=await store.one("SELECT id FROM opportunities WHERE id=?",key)
                if not row: raise Blocked("activity_not_found")
                if not body or set(body)-{"priority","skip","outcome","ineligible"}: raise Blocked("invalid_activity_update")
                if "ineligible" in body:
                    from strategy import project_key
                    full=await store.one("SELECT * FROM opportunities WHERE id=?",key); pk=project_key(full)
                    if body["ineligible"] is True:
                        await store.run("INSERT OR REPLACE INTO ineligible_keys(key,reason,example_id,at) VALUES(?,?,?,?)",pk,"account_rejected",key,now())
                        await store.run("UPDATE opportunities SET skipped=1 WHERE id=?",key)
                    elif body["ineligible"] is False:
                        await store.run("DELETE FROM ineligible_keys WHERE key=?",pk)
                    else: raise Blocked("ineligible_invalid")
                if "priority" in body:
                    p=body["priority"]
                    if type(p) is not int or not -100<=p<=100: raise Blocked("priority_invalid")
                    await store.run("UPDATE opportunities SET priority=? WHERE id=?",p,key)
                if "skip" in body:
                    if type(body["skip"]) is not bool: raise Blocked("skip_invalid")
                    await store.run("UPDATE opportunities SET skipped=? WHERE id=?",int(body["skip"]),key)
                if "outcome" in body:
                    if body["outcome"] not in ("paid","not_paid",None): raise Blocked("outcome_invalid")
                    await store.run("UPDATE opportunities SET outcome=? WHERE id=?",body["outcome"],key)
                await intervened(store,"activity_update",key,key)
                return response({"updated":key})
            if path=="/api/ledger/income":
                entry=income_entry(body,now())
                key=digest(entry)
                await store.run("INSERT OR IGNORE INTO income(id,source_ref,opportunity_id,asset,amount_raw,decimals,usd_micro,price_basis,tx_hash,evidence,received_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                key,entry["source_ref"],entry["opportunity_id"],entry["asset"],entry["amount_raw"],entry["decimals"],
                                entry["usd_micro"],entry["price_basis"],entry["tx_hash"],entry["evidence"],entry["received_at"],now())
                await intervened(store,"record_income",key,entry["opportunity_id"])
                if entry["opportunity_id"]:
                    await store.run("UPDATE opportunities SET outcome='paid' WHERE id=?",entry["opportunity_id"])
                return response({"recorded":key,"realized":(await summary(store))["realized"]})
            if path=="/api/ledger/cost":
                entry=cost_entry(body,now()); key="manual:"+digest(entry)
                await store.run("INSERT OR IGNORE INTO costs(id,category,reserved_micro,actual_micro,state,created_at,evidence,opportunity_id) VALUES(?,?,?,?,?,?,?,?)",
                                key,entry["category"],entry["usd_micro"],entry["usd_micro"],"confirmed",now(),
                                canonical({"tx_hash":entry.get("tx_hash"),"evidence":entry.get("evidence"),"basis":"user_recorded_actual"}),entry.get("opportunity_id"))
                await intervened(store,"record_cost",key,entry.get("opportunity_id"))
                return response({"recorded":key,"realized":(await summary(store))["realized"]})
            if path=="/api/tick":
                if body:
                    raise Blocked("unknown_field")
                return response(await tick(self.env,store))
            if path=="/api/control":
                if set(body)!={"paused"} or type(body["paused"]) is not bool:
                    raise Blocked("invalid_control")
                await store.run("UPDATE control SET paused=? WHERE id=1",int(body["paused"]))
                confirmed=False
                if body["paused"]:
                    try:
                        await executor(self.env,"/pause",{});confirmed=True
                    except Blocked:
                        await store.event("pause:unconfirmed","executor_pause_unconfirmed",{})
                await store.audit("pause" if body["paused"] else "resume_research","control")
                await intervened(store,"pause" if body["paused"] else "resume","control")
                return response({"paused":body["paused"],"executor_paused":confirmed})
            m=re.fullmatch(r"/api/task-handoffs/([a-f0-9]{64})/(approve|reject|complete)",path)
            if m:
                key,action=m.groups(); row=await store.one("SELECT * FROM task_handoffs WHERE id=?",key)
                if not row or row["digest"]!=key: raise Blocked("task_handoff_not_found")
                plan=json.loads(row["plan"])
                if action=="reject":
                    if body: raise Blocked("unknown_field")
                    await store.run("UPDATE task_handoffs SET state='rejected' WHERE id=? AND state='pending_approval'",key)
                    await intervened(store,"task_reject",key,row["opportunity_id"])
                    return response({"state":"rejected","id":key})
                if body.get("digest")!=key: raise Blocked("task_handoff_digest_mismatch")
                if action=="approve":
                    if set(body)!={"digest"}: raise Blocked("invalid_task_handoff_approval")
                    await store.run("UPDATE task_handoffs SET state='approved',approved_at=? WHERE id=? AND state='pending_approval'",now(),key)
                    await intervened(store,"task_approve",key,row["opportunity_id"])
                    return response({"state":"approved","id":key,"plan":plan})
                if not {"digest","evidence"}<=set(body) or set(body)-{"digest","evidence","minutes"}: raise Blocked("invalid_task_handoff_completion")
                if row["state"]!="approved": raise Blocked("task_handoff_not_approved")
                ev=evidence(body["evidence"])
                minutes=body.get("minutes")
                if minutes is not None and (type(minutes) is not int or not 0<=minutes<=1440): raise Blocked("task_minutes_invalid")
                await store.run("UPDATE task_handoffs SET state='completed',completed_at=?,evidence=? WHERE id=?",now(),ev,key)
                await store.run("UPDATE opportunities SET status='task_done_waiting_reward' WHERE id=?",row["opportunity_id"])
                await intervened(store,"task_complete",key,row["opportunity_id"],minutes)
                return response({"state":"completed","id":key})
            m=re.fullmatch(r"/api/proposals/([a-f0-9]{64})/(approve|reject|resume)",path)
            if m:
                key,action=m.groups()
                p=await store.one("SELECT * FROM proposals WHERE id=?",key)
                if not p:
                    return response({"error":"not_found"},404)
                if action=="reject":
                    if body:
                        raise Blocked("unknown_field")
                    changed=await store.one("UPDATE proposals SET state='rejected' WHERE id=? AND state='pending_approval' RETURNING id",key)
                    if not changed:
                        raise Blocked("proposal_not_rejectable")
                    await store.audit("reject",key,p["digest"])
                    await intervened(store,"proposal_reject",key,p["opportunity_id"])
                    return response({"state":"rejected"})
                if set(body)!={"digest","owner_token"} or body["digest"]!=p["digest"]:
                    raise Blocked("approval_digest_mismatch")
                if not isinstance(body["owner_token"],str) or not 32<=len(body["owner_token"])<=256:
                    raise Blocked("owner_token_missing")
                if action=="resume":
                    if p['state'] not in ('approval_submitting','approved','executing','holding'):
                        raise Blocked('proposal_not_resumable')
                    if (await store.one('SELECT paused FROM control WHERE id=1'))['paused']:
                        raise Blocked('research_paused')
                    state=(await executor(self.env,'/state')).get('plan')
                    if not state or state.get('id')!=key:
                        raise Blocked('approval_not_confirmed')
                    await executor(self.env,'/owner/resume',{'id':key},body['owner_token'])
                    await store.audit('user_resumed',key,p['digest'])
                    await intervened(store,"proposal_resume",key,p["opportunity_id"])
                    return response({'state':'resumed','id':key})
                if p["state"]!="pending_approval" or p["expires_at"]<=now():
                    raise Blocked("proposal_not_approvable")
                c=await store.one("SELECT fingerprint,observed_at FROM opportunities WHERE id=?",p["opportunity_id"])
                if not c or c["fingerprint"]!=p["fingerprint"] or now()-c["observed_at"]>3600:
                    raise Blocked("proposal_evidence_stale")
                control=await store.one("SELECT paused FROM control WHERE id=1")
                if control["paused"]:
                    raise Blocked("research_paused")
                details=json.loads(p["plan"]);s=settings(self.env)
                if details['economics']['principal_usd_micro']>s['max_principal_usd_micro']:
                    raise Blocked('principal_limit_changed')
                if digest(details["plan"])!=body["digest"]:
                    raise Blocked("stored_plan_changed")
                # Reject a mistyped owner token before locking a budget reservation.
                await executor(self.env,'/owner/check',{},body['owner_token'])
                amount=details["economics"]["worst_loss_usd_micro"]
                # Atomically reserve worst-case capital plus all quoted costs before contacting signer.
                result=await store.batch([
                    ("""INSERT OR IGNORE INTO costs(id,category,proposal_id,reserved_micro,state,created_at)
                        SELECT ?, 'capital_and_fee_reservation', ?, ?, 'reserved', ?
                        WHERE EXISTS(SELECT 1 FROM proposals WHERE id=? AND state='pending_approval')
                        AND (SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) FROM costs)+?<=?""",
                        ("position:"+key,key,amount,now(),key,amount,s["max_loss_usd_micro"])),
                    ("""UPDATE proposals SET state='approval_submitting',approved_at=? WHERE id=?
                         AND state='pending_approval' AND EXISTS(SELECT 1 FROM costs WHERE id=?) RETURNING id""",
                         (now(),key,"position:"+key))])
                if not result[1]["results"]:
                    raise Blocked("approval_conflict_or_loss_limit")
                await store.audit("user_approved",key,p["digest"])
                await intervened(store,"proposal_approve",key,p["opportunity_id"])
                try:
                    result=await approve(self.env,details["plan"],body["owner_token"])
                    await executor(self.env,"/owner/resume",{'id':key},body["owner_token"])
                except Blocked:
                    await store.event(key+":approval_uncertain","approval_needs_reconciliation",{"id":key},key)
                    raise Blocked("approval_result_uncertain_check_executor") from None
                await store.run("UPDATE proposals SET state='approved',executor_state=? WHERE id=?",canonical(result),key)
                return response({"state":"approved","id":key})
            return response({"error":"not_found"},404)
        except Blocked as e:
            return response({"error":str(e)},409)
        except Exception:
            return response({"error":"internal_error_check_database_and_configuration"},503)

    async def scheduled(self,controller,env=None,ctx=None):
        # Infrequent wake-ups (every 8h): run several bounded steps so one wake-up discovers,
        # screens and analyses instead of doing a single step and sleeping for 8 hours.
        store=Store(self.env.DB);result={"state":"idle"}
        for _ in range(CRON_STEPS):
            result=await tick(self.env,store,cron=True)
            if result["state"] in ("idle","paused","blocked","busy"):
                break
        if result["state"]=="blocked":
            raise RuntimeError(result["reason"])
