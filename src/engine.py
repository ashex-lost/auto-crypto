"""One bounded state-machine step per invocation; cron is only a wake-up signal."""
import json
from common import Blocked, canonical, now
from config import settings
from collector import discover,refresh_merkl
from analyst import analyze
from policy import proposal
from execution import advance,executor
from notifier import deliver
from review import review
from ledger import reconcile_reservation
from valuation import value_position
from economics import estimate,worth_review


async def process_execution(env,store,paused=False):
    p=await store.one("SELECT * FROM proposals WHERE state IN ('approval_submitting','approved','executing','holding') ORDER BY created_at LIMIT 1")
    if not p:
        return False
    if p["state"]=='approval_submitting':
        answer=await executor(env,"/state")
        state=answer.get("plan")
        if not state or state["id"]!=p["id"]:
            await store.run("UPDATE proposals SET state='needs_attention',error_code='approval_not_confirmed' WHERE id=?",p["id"])
            return True
    else:
        # If rules changed before entry, do not enter; approved exits are reconciled by the executor.
        snapshot=(await executor(env,'/state')).get('plan')
        if not snapshot or snapshot.get('id')!=p['id']:
            raise Blocked('approved_plan_missing_in_executor')
        # Pending receipts, revocations and exits must not depend on a research website.
        entering=(snapshot['stage'] in ('approved','allowance_set') and not snapshot.get('pending')
                  and snapshot['plan']['expires_at']>now())
        if entering and not paused:
            try:
                evidence=await refresh_merkl(store,p["opportunity_id"])
                if evidence["fingerprint"]!=p["fingerprint"] or evidence["data"].get("status")!='LIVE':
                    raise Blocked("approved_evidence_changed")
                if entering:
                    e=json.loads(p['plan'])['economics']
                    recalculated=estimate(e['principal_usd_micro'],evidence['data']['apr'],e['days'],e['costs_usd_micro'])
                    if not worth_review(recalculated,settings(env)['min_net_usd_micro']):
                        raise Blocked('entry_no_longer_worthwhile')
            except Blocked:
                await executor(env,"/pause",{})
                raise
        state=await advance(env,p["id"])
    stage=state["stage"]
    old=json.loads(p['executor_state']) if p['executor_state'] else {}
    if len(state.get('receipts',[]))!=len(old.get('receipts',[])) or old.get('valuation',{}).get('as_of',0)<now()-3600:
        state['valuation']=await value_position(state,settings(env))
    elif old.get('valuation'):
        state['valuation']=old['valuation']
    mapped={'approved':'approved','allowance_set':'executing','deposited':'executing','holding':'holding',
            'exited':'holding','closed':'closed','needs_attention':'needs_attention'}[stage]
    await store.run("UPDATE proposals SET state=?,executor_state=?,closed_at=CASE WHEN ?='closed' THEN ? ELSE closed_at END WHERE id=?",
                    mapped,canonical(state),mapped,now(),p["id"])
    await reconcile_reservation(store,p,state)
    if mapped in ('closed','needs_attention') or state.get('attention'):
        await store.event(p["id"]+":"+mapped,"execution_"+mapped,{"id":p["id"]},p["id"])
    return True


async def evaluate(env,store,s,candidate,analysis):
    # Recalculate once per day without paying to re-read unchanged rules.
    await store.run("UPDATE opportunities SET evaluation_due=? WHERE id=?",now()+86400,candidate["id"])
    try:
        p=await proposal(env,store,s,candidate,analysis)
        await store.run("INSERT INTO proposals(id,opportunity_id,fingerprint,plan,digest,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                        p["id"],candidate["id"],candidate["fingerprint"],canonical(p),p["digest"],now(),p["plan"]["expires_at"])
        await store.event(p["id"]+":approve","approval_required",{"id":p["id"]},p["id"])
        return {"state":"awaiting_approval","id":p["id"]}
    except Blocked as e:
        await store.run("UPDATE opportunities SET status=? WHERE id=?",str(e),candidate["id"])
        return {"state":"screened","reason":str(e)}


async def tick(env,store,cron=False):
    t=now(); token=await store.acquire(t)
    if not token:
        return {"state":"busy"}
    error=None
    try:
        s=settings(env)
        control=await store.one("SELECT * FROM control WHERE id=1")
        if s['monthly_fixed_usd_micro'] is not None and not control['paused']:
            from datetime import datetime,timezone
            month=datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m')
            await store.run("INSERT OR IGNORE INTO costs(id,category,reserved_micro,state,created_at,evidence) VALUES(?,?,?,?,?,?)",
                            'hosting:'+month,'hosting',s['monthly_fixed_usd_micro'],'reserved',t,
                            canonical({'basis':'configured_monthly_budget','billing_month':month}))
        # Reconciliation is allowed while paused, but the executor is paused too and cannot sign anew.
        if control["paused"]:
            active=await store.one("SELECT id FROM proposals WHERE state IN ('approved','executing','holding') LIMIT 1")
            if active:
                await executor(env,"/pause",{})
                await process_execution(env,store,paused=True)
            return {"state":"paused"}
        executed=await process_execution(env,store)
        await store.run("UPDATE proposals SET state='expired' WHERE state='pending_approval' AND expires_at<=?",t)
        if control["next_discovery"]<=t:
            # Persist next due time before network I/O. A failed provider cannot create a tight paid loop.
            await store.run("UPDATE control SET next_discovery=?,discovery_page=(discovery_page+1)%10 WHERE id=1",t+s["discovery_seconds"])
            result=await discover(store,control["discovery_page"])
            return {"state":"discovered","sources":result}
        candidate=await store.one("SELECT * FROM opportunities WHERE (analyzed_fingerprint IS NULL OR analyzed_fingerprint!=fingerprint) AND status='discovered' ORDER BY CASE source WHEN 'binance' THEN 0 ELSE 1 END, observed_at DESC LIMIT 1")
        if candidate:
            # Unknown API outcomes are NOT automatically resubmitted after a process restart.
            await store.run("UPDATE opportunities SET status='analyzing' WHERE id=?",candidate["id"])
            try:
                analysis=await analyze(env,store,s,candidate)
            except Blocked as e:
                status='discovered' if str(e) in ('model_key_missing','model_access_not_confirmed','ai_budget_exhausted') else 'analysis_needs_attention'
                await store.run("UPDATE opportunities SET status=? WHERE id=?",status,candidate["id"])
                raise
            await store.run("UPDATE opportunities SET analysis=?,analyzed_fingerprint=fingerprint,last_analyzed=?,status='analyzed' WHERE id=?",canonical(analysis),t,candidate["id"])
            return await evaluate(env,store,s,candidate,analysis)
        cached=await store.one("SELECT * FROM opportunities WHERE analyzed_fingerprint=fingerprint AND analysis IS NOT NULL AND evaluation_due<=? AND observed_at>? ORDER BY evaluation_due LIMIT 1",t,t-86400)
        if cached:
            return await evaluate(env,store,s,cached,json.loads(cached["analysis"]))
        if control["next_review"]<=t:
            await store.run("UPDATE control SET next_review=? WHERE id=1",t+7*86400)
            result=await review(env,store,s)
            return {"state":"reviewed","review":result}
        return {"state":"execution_checked" if executed else "idle"}
    except Blocked as e:
        error=str(e)
        await store.event("block:"+error,"action_required",{"code":error})
        return {"state":"blocked","reason":error}
    except Exception:
        error="internal_error"
        await store.run("UPDATE control SET paused=1 WHERE id=1")
        await store.event("block:internal_error","action_required",{"code":error})
        return {"state":"blocked","reason":error}
    finally:
        try:
            await deliver(env,store)
        except Exception:
            pass  # Outbox remains undelivered and visible; never erase evidence of a failed push.
        await store.release(token,error,cron)
