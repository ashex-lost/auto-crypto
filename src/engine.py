"""One bounded state-machine step per invocation; cron is only a wake-up signal."""
import json
from functools import partial
from common import Blocked, canonical, now
from config import settings
from collector import discover,refresh_merkl
from ai import analyze, review
from policy import proposal, prescreen, SCREENING_VERSION
from execution import advance,executor
from notifier import deliver
from finance import reconcile_reservation, value_position, estimate, worth_review, summary, research_estimate
from network import get_json
from receiver import snapshot
from task_handoff import prepare, GENERIC_STEPS
from config import binding

SCREEN_BATCH=25
REPORT_KIND='periodic_report'


def model_ready(env,s):
    connected=getattr(env,"AI",None) is not None if s.get("provider")=="workers_ai" else bool(binding(env,"MODEL_API_KEY"))
    return s["provider_eligible"] is True and connected and s["monthly_ai_usd_micro"]>0


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
        state['valuation']=await value_position(state,settings(env),read_quote=get_json)
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


def task_facts(data,analysis):
    """Fill unknown task fields with the AI's conservative estimates, and label them as estimates."""
    merged=dict(data); estimated=[]
    def fill(key,value):
        if merged.get(key) is None and value is not None:
            merged[key]=value; estimated.append(key)
    fill('requires_public_post',analysis.get('requires_public_post'))
    fill('requires_accounts',analysis.get('required_accounts'))
    fill('human_minutes',analysis.get('estimated_human_minutes'))
    if analysis.get('deadline_unix'): fill('ends_at',analysis['deadline_unix'])
    if merged.get('reward_kind') in (None,'unannounced') and analysis.get('reward_kind') in ('raffle','points'):
        merged['reward_kind']=analysis['reward_kind']; estimated.append('reward_kind')
    if analysis.get('requires_funds') is False:
        fill('requires_deposit',False); fill('requires_trading',False)
    costs=dict(merged.get('costs_usd_micro') or {})
    def cost(key,value,label=True):
        if costs.get(key) is None and value is not None:
            costs[key]=value
            if label: estimated.append('costs.'+key)
    # Marginal cost of this analysis is known exactly; hosting is a shared fixed cost booked monthly in the ledger.
    cost('ai',analysis.get('analysis_cost_usd_micro'),False); cost('hosting',0,False)
    if analysis.get('requires_funds') is False:
        gasless=(merged.get('official') or {}).get('gasType')=='Gasless'
        cost('trading',0); cost('other',0)
        if gasless: cost('gas',0); cost('claim',0)
    merged['costs_usd_micro']=costs
    if not merged.get('steps') and analysis.get('manual_steps'):
        merged['steps']=analysis['manual_steps'][:30]; estimated.append('steps')
    return merged,estimated


async def activity_ev(store,s,candidate,analysis,screened=None):
    """Compute and store EV for one activity; history makes each category's estimate self-correcting."""
    from strategy import category, expected_value, category_history, CATEGORIES
    data=json.loads(candidate["data"]) if isinstance(candidate["data"],str) else candidate["data"]
    cat=category(candidate)
    if candidate.get("source")=="task" and (analysis or {}).get("category") in CATEGORIES and cat in ("points_task","other"):
        cat=analysis["category"]
    known=(screened or {}).get("known_cost_usd_micro")
    missing=(screened or {}).get("missing_costs")
    official=data.get("official") or {}
    a=analysis or {}
    facts={"cash_cost_usd":None if missing else (known or 0)/1e6,
           "human_minutes":data.get("human_minutes",a.get("estimated_human_minutes")),
           "ai_cost_usd":a.get("analysis_cost_usd_micro",0)/1e6,
           "per_person_usd":(data.get("reward_per_person_usd_micro") or 0)/1e6 or a.get("per_person_usd") or None,
           "pool_usd":a.get("reward_pool_usd") or None,"winners":a.get("winners_count") or None,
           "participants":official.get("participantsCount") or None}
    history=(await category_history(store)).get(cat)
    ev=expected_value(cat,facts,s,history)
    await store.run("UPDATE opportunities SET ev=? WHERE id=?",canonical(ev),candidate["id"])
    return ev


async def evaluate_task(store,s,candidate,analysis):
    """Tasks never reach the wallet executor. At most they become a manual handoff you approve."""
    data,estimated=task_facts(json.loads(candidate["data"]),analysis)
    screened=prescreen({**candidate,"data":data},None,s)
    blockers=list(screened.get('handoff_blockers',[]))
    if analysis.get("recommendation")=="reject": blockers.append('ai_rejected')
    if analysis.get("borrowing_required") is not False: blockers.append('borrowing_or_unknown')
    if analysis.get("eligibility")=="not_eligible": blockers.append('not_eligible')
    if analysis.get("manual_participation")!="allowed": blockers.append('manual_participation_not_confirmed')
    if analysis.get("requires_funds") is not False: blockers.append('needs_separate_funding_plan')
    check=await store.one("SELECT result FROM task_checks WHERE opportunity_id=? AND status='checked'",candidate["id"])
    qualification=json.loads(check["result"]).get("qualification") if check and check["result"] else None
    if qualification=='conditions_not_met': blockers.append('wallet_conditions_not_met')
    # Expected value replaces the old "fixed reward only" rule: raffles and points can pass if EV is high.
    ev=await activity_ev(store,s,{**candidate,"data":data},analysis,screened)
    blockers=[b for b in blockers if b not in ('net_after_time_unknown','net_below_threshold','reward_value_unknown_research_only')]
    if ev["ev_usd"] is None: blockers.append('ev_unknown')
    elif ev["ev_usd"]*1e6<s['min_net_usd_micro']: blockers.append('ev_below_threshold')
    if blockers:
        await store.run("UPDATE opportunities SET status='task_review_needed',screening=? WHERE id=?",
                        canonical({**screened,'handoff_blockers':blockers}),candidate["id"])
        return {"state":"task_review_needed","blockers":blockers}
    # One handoff per activity version; a rejection is respected until the official rules change.
    existing=await store.one("SELECT id FROM task_handoffs WHERE opportunity_id=? AND state!='expired' AND json_extract(plan,'$.context.fingerprint_hint')=?",candidate["id"],candidate["fingerprint"][:16])
    if existing:
        return {"state":"task_handoff_exists","id":existing["id"]}
    if not data.get('steps') and data.get('adapter')=='galxe_read_v1':
        data['steps']=GENERIC_STEPS
    context={"ends_at":data.get("ends_at"),"reward_kind":data.get("reward_kind"),
             "requires_public_post":data.get("requires_public_post"),"required_accounts":data.get("requires_accounts"),
             "human_minutes":data.get("human_minutes"),"net_after_time_usd_micro":screened.get("net_after_time_usd_micro"),
             "known_cost_usd_micro":screened.get("known_cost_usd_micro"),"eligibility":analysis.get("eligibility"),
             "qualification":qualification,"ai_estimated_fields":estimated,
             "fingerprint_hint":candidate["fingerprint"][:16],
             "ev":ev,
             "warnings":["奖励可能为零；抽奖/积分/未公布空投不计收入。"]+(["需要公开发帖，内容由你本人撰写并决定是否发布。"] if data.get("requires_public_post") else [])
                        +(["资格未完全确认，请在官方页面核对。"] if analysis.get("eligibility")!="confirmed" else [])}
    try:
        handoff=prepare({**data,"title":candidate["title"],"url":candidate["url"]},context=context)
    except Blocked as e:
        await store.run("UPDATE opportunities SET status=? WHERE id=?",str(e),candidate["id"])
        return {"state":"task_review_needed","blockers":[str(e)]}
    await store.run("INSERT OR IGNORE INTO task_handoffs(id,opportunity_id,digest,plan,state,created_at) VALUES(?,?,?,?,?,?)",
                    handoff["id"],candidate["id"],handoff["digest"],canonical(handoff["plan"]),"pending_approval",now())
    await store.run("UPDATE opportunities SET status='task_handoff_pending' WHERE id=?",candidate["id"])
    await store.event(handoff["id"]+":task_approval","task_handoff_approval_required",
                      {"id":handoff["id"],"title":handoff["plan"]["title"],"url":handoff["plan"]["url"],
                       "steps":handoff["plan"]["steps"],"context":handoff["plan"]["context"]})
    return {"state":"task_handoff_approval","id":handoff["id"]}


async def evaluate(env,store,s,candidate,analysis):
    # Recalculate once per day without paying to re-read unchanged rules.
    await store.run("UPDATE opportunities SET evaluation_due=? WHERE id=?",now()+86400,candidate["id"])
    if candidate["source"]=="task":
        return await evaluate_task(store,s,candidate,analysis)
    screened=prescreen(candidate,None,s)
    if not screened['eligible_for_analysis']:
        await store.run("UPDATE opportunities SET screening=?,screening_version=?,status='screened_out' WHERE id=?",
                        canonical(screened),SCREENING_VERSION,candidate['id'])
        return {'state':'screened','reasons':screened['reasons']}
    try:
        p=await proposal(store,s,candidate,analysis,preview_vault=partial(executor,env,"/preview"))
        await store.run("INSERT INTO proposals(id,opportunity_id,fingerprint,plan,digest,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                        p["id"],candidate["id"],candidate["fingerprint"],canonical(p),p["digest"],now(),p["plan"]["expires_at"])
        await store.event(p["id"]+":approve","approval_required",
                          {"id":p["id"],"title":candidate["title"],"url":candidate["url"],"summary":p["summary"],
                           "permissions":p["permissions"]},p["id"])
        return {"state":"awaiting_approval","id":p["id"]}
    except Blocked as e:
        await store.run("UPDATE opportunities SET status=? WHERE id=?",str(e),candidate["id"])
        return {"state":"screened","reason":str(e)}


async def flag_incoming(store,observed,t):
    """A balance increase is only a hint to record income; it is never booked automatically."""
    if observed.get("status")!="ok":
        return
    prev=await store.one("SELECT native_raw,assets FROM receiver_snapshots WHERE status='ok' AND address=? AND chain_id=? ORDER BY observed_at DESC LIMIT 1",
                         observed["address"],observed["chain_id"])
    if not prev:
        return
    old={a["address"]:int(a["raw"]) for a in json.loads(prev["assets"] or "[]")}
    increases=[{"asset":a["symbol"],"token":a["address"],"delta_raw":str(int(a["raw"])-old[a["address"]]),"decimals":a["decimals"]}
               for a in observed.get("assets",[]) if a["address"] in old and int(a["raw"])>old[a["address"]]]
    native_delta=int(observed["native_raw"])-int(prev["native_raw"] or 0)
    if native_delta>0:
        increases.append({"asset":"native","delta_raw":str(native_delta),"decimals":18})
    if increases:
        await store.event("receiver:%d:%d"%(observed["chain_id"],t),"receiver_balance_increased",
                          {"increases":increases,"note":"请核对来源；是奖励就在控制台登记到账，不自动记为收入。"})


async def periodic_report(store,s,t):
    """Deterministic, free report on a fixed cadence; the optional AI review is separate."""
    control=await store.one("SELECT next_report FROM control WHERE id=1")
    if control["next_report"]==0:
        await store.run("UPDATE control SET next_report=? WHERE id=1",t+s["report_days"]*86400)
        return None
    if control["next_report"]>t:
        return None
    await store.run("UPDATE control SET next_report=? WHERE id=1",t+s["report_days"]*86400)
    from finance import metrics
    report=await metrics(store,t-s["report_days"]*86400)
    await store.run("INSERT OR IGNORE INTO reviews(id,created_at,data) VALUES(?,?,?)","report:%d"%t,t,canonical({"type":"metrics",**report}))
    await store.event("report:%d"%t,REPORT_KIND,{"realized":report["realized"],"human_interventions":report["human_interventions"],
                      "human_minutes":report["human_minutes_reported"],"funnel":report["funnel"],"model_usage":report["model_usage"]})
    return report


async def tick(env,store,cron=False):
    t=now(); token=await store.acquire(t)
    if not token:
        return {"state":"busy"}
    error=None
    try:
        from config import load_settings
        s=await load_settings(env,store)
        control=await store.one("SELECT * FROM control WHERE id=1")
        # Receiver is read-only and intentionally independent of signing/execution.
        # A missing RPC or address becomes an observation, never a reason to stop research.
        try:
            observed=await snapshot(env,s)
            await flag_incoming(store,observed,t)
            await store.run("INSERT INTO receiver_snapshots(observed_at,status,chain_id,address,native_raw,assets) VALUES(?,?,?,?,?,?)",
                            t,observed.get("status","unknown"),observed.get("chain_id"),observed.get("address"),
                            observed.get("native_raw"),canonical(observed.get("assets",[])))
        except Blocked as e:
            await store.run("INSERT INTO receiver_snapshots(observed_at,status,error_code) VALUES(?,?,?)",
                            t,"error",str(e))
        if s['monthly_fixed_usd_micro'] is not None and not control['paused']:
            from datetime import datetime,timezone
            month=datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m')
            await store.run("INSERT OR IGNORE INTO costs(id,category,reserved_micro,state,created_at,evidence) VALUES(?,?,?,?,?,?)",
                            'hosting:'+month,'hosting',s['monthly_fixed_usd_micro'],'reserved',t,
                            canonical({'basis':'configured_monthly_budget','billing_month':month}))
        # Hard stop: realized loss (all costs incl. AI/API/hosting, minus actual receipts) reached the cap.
        if not control["paused"] and s["max_loss_usd_micro"]>0:
            from finance import realized
            r=await realized(store)
            if r["costs_usd_micro"]+r["open_risk_reservation_usd_micro"]-r["income_usd_micro"]>=s["max_loss_usd_micro"]:
                await store.run("UPDATE control SET paused=1 WHERE id=1")
                await store.event("loss_cap:%d"%s["max_loss_usd_micro"],"loss_cap_reached",{"realized":r})
                control=dict(control); control["paused"]=1
        # Reconciliation is allowed while paused, but the executor is paused too and cannot sign anew.
        if control["paused"]:
            active=await store.one("SELECT id FROM proposals WHERE state IN ('approved','executing','holding') LIMIT 1")
            if active:
                await executor(env,"/pause",{})
                await process_execution(env,store,paused=True)
            return {"state":"paused"}
        executed=await process_execution(env,store)
        await store.run("UPDATE proposals SET state='expired' WHERE state='pending_approval' AND expires_at<=?",t)
        await store.run("UPDATE task_handoffs SET state='expired' WHERE state IN ('pending_approval','approved') AND CAST(json_extract(plan,'$.context.ends_at') AS INTEGER) BETWEEN 1 AND ?",t)
        # A completed task with no recorded payout 30 days after its deadline counts as "not paid",
        # so raffle-style categories learn their real hit rate without you marking every loss.
        await store.run("""UPDATE opportunities SET outcome='not_paid' WHERE outcome IS NULL AND status='task_done_waiting_reward'
            AND CAST(json_extract(data,'$.ends_at') AS INTEGER) BETWEEN 1 AND ?""",t-30*86400)
        await periodic_report(store,s,t)
        if control["next_discovery"]<=t:
            # Persist next due time before network I/O. A failed provider cannot create a tight paid loop.
            await store.run("UPDATE control SET next_discovery=?,discovery_page=(discovery_page+1)%10 WHERE id=1",t+s["discovery_seconds"])
            result=await discover(store,control["discovery_page"],env)
            from galxe import check_next
            checked = await check_next(env,store)
            return {"state":"discovered","sources":result,"task_qualification":checked}
        # Free fixed-rule screening of a whole batch; no model, wallet or network cost.
        batch=await store.all("SELECT * FROM opportunities WHERE (analyzed_fingerprint IS NULL OR analyzed_fingerprint!=fingerprint) AND (status='discovered' OR (status IN ('screened_out','awaiting_ai') AND COALESCE(screening_version,'')!=?)) ORDER BY CASE source WHEN 'task' THEN 0 ELSE 1 END, observed_at DESC LIMIT ?",SCREENING_VERSION,SCREEN_BATCH)
        passed=0
        for row in batch:
            screened=prescreen(row,t,s)
            screened['cost_estimate']=research_estimate(json.loads(row['data']),s)
            screened['checked_at']=t
            ok=screened['eligible_for_analysis']; passed+=int(ok)
            await store.run("UPDATE opportunities SET screening=?,screening_version=?,status=? WHERE id=?",
                            canonical(screened),SCREENING_VERSION,'awaiting_ai' if ok else 'screened_out',row['id'])
        if model_ready(env,s):
            candidate=await store.one("SELECT * FROM opportunities WHERE status='awaiting_ai' AND skipped=0 AND (analyzed_fingerprint IS NULL OR analyzed_fingerprint!=fingerprint) AND observed_at>? ORDER BY priority DESC, CASE source WHEN 'task' THEN 0 WHEN 'bounty' THEN 0 ELSE 1 END, observed_at DESC LIMIT 1",t-86400)
            if candidate:
                # Unknown API outcomes are NOT automatically resubmitted after a process restart.
                await store.run("UPDATE opportunities SET status='analyzing' WHERE id=?",candidate["id"])
                try:
                    analysis=await analyze(env,store,s,candidate)
                except Blocked as e:
                    status='awaiting_ai' if str(e) in ('model_key_missing','model_access_not_confirmed','ai_budget_exhausted') else 'analysis_needs_attention'
                    await store.run("UPDATE opportunities SET status=? WHERE id=?",status,candidate["id"])
                    raise
                await store.run("UPDATE opportunities SET analysis=?,analyzed_fingerprint=fingerprint,last_analyzed=?,status='analyzed' WHERE id=?",canonical(analysis),t,candidate["id"])
                return await evaluate(env,store,s,candidate,analysis)
        elif passed:
            # Research continues without AI: candidates wait, nothing is guessed, one deduplicated notice.
            await store.event("ai:not_configured","ai_analysis_waiting",{"code":"model_not_configured"})
        if batch:
            return {"state":"screened","screened":len(batch),"passed_rules":passed,
                    "reasons":json.loads((await store.one("SELECT screening FROM opportunities WHERE id=?",batch[0]['id']))['screening'])['reasons']}
        cached=await store.one("SELECT * FROM opportunities WHERE analyzed_fingerprint=fingerprint AND analysis IS NOT NULL AND evaluation_due<=? AND observed_at>? ORDER BY evaluation_due LIMIT 1",t,t-86400)
        if cached:
            return await evaluate(env,store,s,cached,json.loads(cached["analysis"]))
        if s['review_enabled'] and control["next_review"]<=t:
            await store.run("UPDATE control SET next_review=? WHERE id=1",t+7*86400)
            ledger=await summary(store)
            ledger["positions"]=[{k:v for k,v in row.items() if k!='receipts'} for row in ledger["positions"][:5]]
            counts=await store.all("SELECT status,COUNT(*) AS count FROM opportunities GROUP BY status")
            from finance import metrics
            result=await review(env,store,s,{"ledger":ledger,"screening":counts,"metrics":await metrics(store,t-30*86400)})
            reviewed_at=now()
            await store.run("INSERT INTO reviews(id,created_at,data) VALUES(?,?,?)",str(reviewed_at),reviewed_at,canonical(result))
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
