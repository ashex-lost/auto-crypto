"""Mobile-first console. Tokens stay in memory (or this device's storage if you tick "remember");
external text is only ever inserted as text, never as HTML."""
PAGE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f1720"><title>空投实验控制台</title>
<style>
:root{--bg:#0f1720;--card:#18232f;--line:#263545;--text:#e8eef4;--muted:#93a4b5;--accent:#5fb3ff;--good:#3ecf8e;--bad:#ff6b6b;--warn:#ffc35a;--chip:#223244}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",system-ui,sans-serif;-webkit-text-size-adjust:100%}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 16px 10px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:10px}
header h1{font-size:18px;margin:0}main{padding:12px 16px 96px;max-width:760px;margin:0 auto}
.pill{font-size:13px;padding:3px 10px;border-radius:99px;background:var(--chip);white-space:nowrap}.pill.on{color:var(--good)}.pill.off{color:var(--warn)}
nav{position:fixed;bottom:0;left:0;right:0;display:flex;background:#121c27;border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom);z-index:5}
nav a{flex:1;text-align:center;padding:9px 0 8px;color:var(--muted);text-decoration:none;font-size:12px}nav a b{display:block;font-size:19px;font-weight:400}nav a.cur{color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:10px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}
.stat small{color:var(--muted);display:block;font-size:12px}.stat b{font-size:20px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 0;border-bottom:1px solid var(--line)}.row:last-child{border-bottom:0}
.row .t{flex:1;min-width:0}.row .t div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row small,.muted{color:var(--muted);font-size:13px}
.ev{font-weight:600;white-space:nowrap}.pos{color:var(--good)}.neg{color:var(--bad)}.unk{color:var(--muted)}
button,.btn{font:inherit;border:0;border-radius:11px;padding:11px 14px;background:var(--accent);color:#06121e;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block;text-align:center}
button.ghost{background:var(--chip);color:var(--text)}button.danger{background:#ff8a80;color:#2b0705}button:disabled{opacity:.5}
.btns{display:flex;gap:8px;flex-wrap:wrap}.btns>*{flex:1}
input,select{font:inherit;width:100%;padding:11px 12px;border-radius:11px;border:1px solid var(--line);background:#0c141c;color:var(--text)}
label{display:block;margin:10px 0 4px;color:var(--muted);font-size:13px}
details{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:10px 0}details>summary{list-style:none;padding:13px 14px;cursor:pointer;display:flex;justify-content:space-between;gap:8px}
details>summary::-webkit-details-marker{display:none}details>summary:after{content:"›";color:var(--muted);transform:rotate(90deg)}details[open]>summary:after{transform:rotate(-90deg)}details .in{padding:0 14px 12px}
.chips{display:flex;gap:6px;overflow-x:auto;padding:4px 0}.chip{background:var(--chip);color:var(--text);border-radius:99px;padding:6px 12px;font-size:14px;white-space:nowrap;border:0}.chip.cur{background:var(--accent);color:#06121e}
.tag{font-size:12px;padding:2px 8px;border-radius:99px;background:var(--chip);color:var(--muted);white-space:nowrap}.tag.go{color:var(--good)}.tag.wait{color:var(--warn)}
.dot{display:inline-block;width:9px;height:9px;border-radius:9px;margin-right:6px;background:var(--muted)}.dot.ok{background:var(--good)}.dot.err{background:var(--bad)}
h2{font-size:16px;margin:18px 0 6px}ol{padding-left:20px;margin:6px 0}a{color:var(--accent)}
#toast{position:fixed;left:16px;right:16px;bottom:78px;background:#263a4f;padding:12px 14px;border-radius:12px;display:none;z-index:9}
.stepper{display:flex;align-items:center;gap:8px}.stepper button{width:44px;padding:9px 0}.stepper span{min-width:36px;text-align:center;font-weight:600}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:var(--muted)}
</style></head><body>
<header><h1>空投实验控制台</h1><span id="pill" class="pill">未登录</span></header>
<main id="view"></main><div id="toast"></div>
<nav id="nav">
<a href="#home" data-t="home"><b>⌂</b>首页</a><a href="#todo" data-t="todo"><b>✓</b>待办</a><a href="#acts" data-t="acts"><b>☰</b>活动</a><a href="#review" data-t="review"><b>◔</b>复盘</a><a href="#set" data-t="set"><b>⚙</b>设置</a></nav>
<script>
"use strict";
const $=id=>document.getElementById(id);
function h(tag,attrs,...kids){const e=document.createElement(tag);for(const[k,v]of Object.entries(attrs||{})){if(v==null||v===false)continue;if(k.startsWith('on'))e.addEventListener(k.slice(2),v);else if(k==='class')e.className=v;else e.setAttribute(k,v===true?'':v);}for(const c of kids.flat()){if(c==null||c===false)continue;e.append(c instanceof Node?c:document.createTextNode(String(c)));}return e;}
let TOKEN='';try{TOKEN=localStorage.getItem('ac_token')||'';}catch(e){}
function toast(t){const e=$('toast');e.textContent=t;e.style.display='block';clearTimeout(toast.t);toast.t=setTimeout(()=>e.style.display='none',3500);}
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json().catch(()=>({}));if(r.status===401){TOKEN='';throw Error('密钥不对或已失效，请重新输入');}if(!r.ok)throw Error(zh(d.error||'请求失败'));return d;}
const ERR={unauthorized:'密钥不对',binance_listing_unreadable:'Binance 公告暂时读取失败',binance_schema_changed:'Binance 公告格式变了',merkl_schema_changed:'Merkl 数据格式变了',upstream_unavailable:'对方网站暂时连不上',model_access_not_confirmed:'AI 尚未开启',model_key_missing:'AI 未连接',ai_budget_exhausted:'今天的 AI 额度用完了',workers_ai_failed:'AI 调用失败，下次重试',model_schema_invalid:'AI 回答格式不对',research_paused:'系统已暂停',executor_not_connected:'签名服务未连接',activity_not_found:'找不到这个活动',approval_digest_mismatch:'方案已变化，请刷新',task_handoff_not_approved:'请先批准这个任务',income_evidence_required:'请填写交易哈希或证据',cost_evidence_required:'请填写交易哈希或证据',override_field_not_allowed:'这个设置不能在控制台修改',internal_error_check_database_and_configuration:'服务器内部错误'};
function zh(c){if(ERR[c])return ERR[c];const m=/^upstream_http_(\d+)$/.exec(c||'');if(m)return '对方网站返回 '+m[1];const b=/^binance_(cms|html)_(.+)$/.exec(c||'');if(b)return 'Binance '+(b[1]==='cms'?'公告接口':'网页')+'：'+zh(b[2]);return c;}
const REASON={source_stale:'资料过期，等下次刷新',campaign_not_live:'活动未开始或已结束',campaign_dates_unknown:'缺少截止时间',chain_unsupported:'这条链暂不支持',borrowing_or_leverage:'需要借贷或杠杆',activity_type_unsupported:'参与方式暂不支持',asset_review_needed:'本金资产需核查',reward_conversion_needed:'奖励不是同种币',binance_execution_unverified:'Binance 活动需你在 App 内参加',binance_terms_missing:'只有公告标题，规则要看原文',deadline_unknown:'截止时间不明',task_ended:'已结束',deadline_too_close:'不到 12 小时就截止',automation_not_verified:'未确认允许自动化',eligibility_not_verified:'资格未确认',trading_requirement_or_unknown:'可能要求交易',deposit_requirement_or_unknown:'可能要求存款',public_post_needs_separate_approval:'需要公开发帖',reward_terms_unknown:'奖励规则不明',account_not_available:'需要你没有的账户',previously_ineligible:'同类项目曾拒绝你的账户',task_not_active:'任务未开放',task_outside_window:'不在任务时间内',task_full:'名额已满',task_dates_unknown:'任务时间不明',task_capacity_unknown:'名额不明',ev_unknown:'期望收益算不出来（成本或时间未知）',ev_below_threshold:'期望收益太低',ai_rejected:'AI 判断不值得',borrowing_or_unknown:'可能需要借贷',manual_participation_not_confirmed:'未确认允许手动参与',needs_separate_funding_plan:'需要投入资金，单独出方案',wallet_conditions_not_met:'钱包不满足条件',cash_cost_unknown:'现金成本未知',eligible_for_analysis:'通过初筛',activity_adapter_review_needed:'需先人工核查合约',net_return_below_threshold_or_cost_unknown:'收益不够或成本未知',one_active_plan_limit:'已有一个进行中的方案'};
const STATUS={discovered:['新发现',''],awaiting_ai:['等待 AI 分析','wait'],analyzing:['分析中','wait'],analyzed:['已分析',''],screened_out:['已筛掉',''],task_review_needed:['资料不足',''],task_handoff_pending:['待你批准','go'],task_done_waiting_reward:['等待到账','wait'],analysis_needs_attention:['分析出错','']};
const CAT={bounty:'AI 悬赏',onchain_usage:'链上使用',fixed_task:'固定奖励任务',points_deposit:'存款积分',testnet:'测试网',raffle:'抽奖',points_task:'积分任务',exchange:'交易所活动',other:'其他'};
const KIND={fixed:'每人固定',raffle:'抽奖',points:'积分',unannounced:'未公布',unknown:'未知'};const day=t=>new Date(t*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
const usd=v=>v==null?'未知':(v<0?'-':'')+'$'+Math.abs(v).toFixed(Math.abs(v)<10?2:0);
const micro=v=>v==null?null:v/1e6;const pct=v=>v==null?'—':Math.round(v*100)+'%';
function ago(ts){if(!ts)return '从未';const s=Date.now()/1000-ts;if(s<90)return '刚刚';if(s<3600)return Math.round(s/60)+' 分钟前';if(s<86400)return Math.round(s/3600)+' 小时前';return Math.round(s/86400)+' 天前';}
function nextRun(){const n=new Date();for(let i=0;i<48;i++){const d=new Date(Date.UTC(n.getUTCFullYear(),n.getUTCMonth(),n.getUTCDate(),0,17)+i*3600e3);if(d.getUTCHours()%8===0&&d>n)return d.toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});}return '—';}
function evSpan(v){return h('span',{class:'ev '+(v==null?'unk':v>=0?'pos':'neg')},usd(v));}
function status(s){const x=STATUS[s]||[REASON[s]||zh(s)||s,''];return h('span',{class:'tag '+x[1]},x[0]);}
let BOOT=null,BOOT_AT=0,LOADING=null;try{const c=JSON.parse(localStorage.getItem('ac_boot')||'null');if(c){BOOT=c.d;BOOT_AT=0;}}catch(e){}
function fetchBoot(){if(!LOADING)LOADING=api('bootstrap').then(d=>{BOOT=d;BOOT_AT=Date.now();LOADING=null;try{localStorage.setItem('ac_boot',JSON.stringify({d}));}catch(e){}return d;},e=>{LOADING=null;throw e;});return LOADING;}
async function load(keys){const extra=keys.filter(k=>!['strategy','status','metrics','receiver','task-handoffs','settings'].includes(k));
 const out={};await Promise.all(extra.map(async k=>{out[k]=await api(k);}));
 if(!BOOT)await fetchBoot();
 else if(Date.now()-BOOT_AT>20000){const at=location.hash;fetchBoot().then(()=>{if(location.hash===at&&!document.activeElement.matches('input,select'))route();}).catch(()=>{});}
 for(const k of keys)if(!(k in out))out[k]=BOOT[k];return out;}
function fresh(){BOOT_AT=0;}
function view(...kids){$('view').replaceChildren(...kids.flat(2).filter(x=>x!=null&&x!==false).map(x=>x instanceof Node?x:document.createTextNode(String(x))));window.scrollTo(0,0);}
function login(){view(h('div',{class:'card'},h('h2',{},'输入控制台访问密钥'),h('input',{id:'tk',type:'password',autocomplete:'off',placeholder:'ADMIN_TOKEN'}),
 h('label',{},h('input',{id:'rm',type:'checkbox',style:'width:auto;margin-right:6px'}),'在这台设备上记住（别人拿到设备也能进入）'),
 h('button',{onclick:async()=>{TOKEN=$('tk').value.trim();try{await api('readiness');try{if($('rm').checked)localStorage.setItem('ac_token',TOKEN);}catch(e){}route();}catch(e){toast(e.message);}}},'进入')));}
async function act(fn,ok){try{await fn();if(ok)toast(ok);await fetchBoot();route();}catch(e){toast(e.message);}}

async function home(){const d=await load(['status','metrics','receiver']);const r=d.status.runtime;const m=d.metrics;
 $('pill').textContent=r.paused?'已暂停':'运行中';$('pill').className='pill '+(r.paused?'off':'on');
 const src=(r.sources||[]).map(s=>h('div',{class:'row'},h('div',{class:'t'},h('div',{},h('span',{class:'dot '+(s.last_error?'err':'ok')}),s.id==='merkl'?'Merkl 链上活动':s.id==='binance'?'Binance 公告':s.id==='galxe'?'Galxe 任务':s.id),h('small',{},s.last_error?zh(s.last_error):'正常 · '+ago(s.last_ok)+' · 本次 '+s.observed_count+' 个'))));
 const snap=(d.receiver.snapshots||[]).find(x=>x.status==='ok');
 view(h('div',{class:'card'},h('div',{},'上次检查：',h('b',{},ago(r.last_tick))),h('div',{class:'muted'},'下次自动检查：'+nextRun()+(r.error?' · 上次出错：'+zh(r.error):''))),
  h('div',{class:'grid'},h('div',{class:'stat'},h('small',{},'已实现净收益'),evSpan(micro(m.realized.realized_net_usd_micro))),h('div',{class:'stat'},h('small',{},'累计到账'),h('b',{},usd(micro(m.realized.income_usd_micro)))),
   h('div',{class:'stat'},h('small',{},'累计费用（含 AI）'),h('b',{},usd(micro(m.realized.costs_usd_micro)))),h('div',{class:'stat'},h('small',{},'你的人工'),h('b',{},m.human_interventions+' 次 / '+m.human_minutes_reported+' 分'))),
  h('h2',{},'数据来源'),h('div',{class:'card'},src.length?src:h('div',{class:'muted'},'还没有运行记录')),
  h('h2',{},'钱包'),h('div',{class:'card'},d.receiver.address?[h('div',{class:'muted'},d.receiver.address),h('div',{},snap?'ETH 余额：'+(Number(snap.native_raw)/1e18).toFixed(5)+'（'+ago(snap.observed_at)+'）':'等待第一次读取')]:h('div',{class:'muted'},'未设置，去「设置」填写')),
  h('div',{class:'btns',style:'margin-top:14px'},h('button',{class:'ghost',onclick:()=>act(()=>api('tick',{}),'已运行一次检查')},'立即检查'),
   r.paused?h('button',{onclick:()=>act(()=>api('control',{paused:false}),'已恢复')},'恢复'):h('button',{class:'danger',onclick:()=>act(()=>api('control',{paused:true}),'已暂停')},'暂停')));}

async function todo(){const d=await load(['task-handoffs','status']);const hs=d['task-handoffs'].handoffs.filter(x=>x.state==='pending_approval'||x.state==='approved');
 const ps=d.status.proposals.filter(p=>p.state==='pending_approval');const evs=d.status.events.filter(e=>/action_required|needs_reconciliation|loss_cap|pause_unconfirmed/.test(e.kind)).slice(0,5);
 const card=(x)=>{const c=x.plan.context||{};return h('a',{href:'#handoff/'+x.id,class:'row',style:'color:inherit;text-decoration:none'},h('div',{class:'t'},h('div',{},x.plan.title),h('small',{},(x.state==='approved'?'已批准，等你完成 · ':'')+(c.human_minutes!=null?'约 '+c.human_minutes+' 分钟 · ':'')+(c.ends_at?'截止 '+new Date(c.ends_at*1000).toLocaleDateString('zh-CN'):''))),evSpan(c.ev&&c.ev.ev_usd));};
 view(h('h2',{},'任务（需要你登录/提交）'),h('div',{class:'card'},hs.length?hs.map(card):h('div',{class:'muted'},'暂时没有，系统会在找到期望收益为正的活动时通知你')),
  h('h2',{},'资金方案（需要你批准）'),h('div',{class:'card'},ps.length?ps.map(p=>h('a',{href:'#proposal/'+p.id,class:'row',style:'color:inherit;text-decoration:none'},h('div',{class:'t'},h('div',{},(p.details.summary||{})['合约']||p.id.slice(0,10)),h('small',{},'本金 '+usd(micro(p.details.economics.principal_usd_micro))+' · 最坏损失 '+usd(micro(p.details.economics.worst_loss_usd_micro)))),evSpan(micro(p.details.economics.net_scenarios_usd_micro&&p.details.economics.net_scenarios_usd_micro.conservative)))):h('div',{class:'muted'},'暂时没有')),
  evs.length?[h('h2',{},'提醒'),h('div',{class:'card'},evs.map(e=>{let c='';try{c=JSON.parse(e.payload).code||'';}catch(x){}return h('div',{class:'row'},h('div',{class:'t'},h('div',{},zh(c)||e.kind),h('small',{},ago(e.created_at))));}))]:null);}

async function handoff(id){const d=await load(['task-handoffs']);const x=d['task-handoffs'].handoffs.find(y=>y.id===id);if(!x)return view(h('div',{class:'card'},'找不到这个任务'));const c=x.plan.context||{};
 view(h('a',{href:'#todo'},'‹ 返回待办'),h('div',{class:'card'},h('h2',{style:'margin-top:0'},x.plan.title),h('div',{},'期望收益：',evSpan(c.ev&&c.ev.ev_usd)),h('div',{class:'muted'},'奖励类型：'+(KIND[c.reward_kind]||'未知')+(c.human_minutes!=null?' · 约 '+c.human_minutes+' 分钟':'')+(c.ends_at?' · 截止 '+day(c.ends_at):'')),
  h('a',{class:'btn',style:'margin-top:10px;width:100%',href:x.plan.url,target:'_blank',rel:'noopener noreferrer'},'打开官方页面')),
  h('details',{open:true},h('summary',{},'步骤'),h('div',{class:'in'},h('ol',{},x.plan.steps.map(s=>h('li',{},s))))),
  (c.warnings||[]).length?h('div',{class:'card muted'},c.warnings.map(w=>h('div',{},'⚠ '+w))):null,
  x.state==='pending_approval'?h('div',{class:'btns'},h('button',{onclick:()=>act(()=>api('task-handoffs/'+x.id+'/approve',{digest:x.digest}),'已批准')},'批准'),h('button',{class:'ghost',onclick:()=>act(()=>api('task-handoffs/'+x.id+'/reject',{}),'已拒绝')},'拒绝')):
  x.state==='approved'?h('div',{class:'card'},h('label',{},'完成证据（截图说明/页面状态）'),h('input',{id:'evd'}),h('label',{},'实际用时（分钟）'),h('input',{id:'mins',inputmode:'numeric'}),h('button',{style:'margin-top:10px;width:100%',onclick:()=>act(()=>{const b={digest:x.digest,evidence:$('evd').value};if($('mins').value)b.minutes=parseInt($('mins').value,10);return api('task-handoffs/'+x.id+'/complete',b);},'已登记完成')},'标记完成')):null);}

async function proposal(id){const d=await load(['status']);const p=d.status.proposals.find(y=>y.id===id);if(!p)return view(h('div',{class:'card'},'找不到这个方案'));const s=p.details.summary||{};
 view(h('a',{href:'#todo'},'‹ 返回待办'),h('div',{class:'card'},Object.entries(s).map(([k,v])=>h('div',{class:'row'},h('div',{class:'t muted'},k.replace(/_/g,' ')),h('div',{},String(v))))),
  h('details',{},h('summary',{},'授权范围'),h('div',{class:'in'},(p.details.permissions||[]).map(x=>h('div',{class:'muted'},x.action+' · '+(x.contract||x.spender||'')+(x.unlimited===false?' · 精确额度':''))))),
  p.state==='pending_approval'?h('div',{class:'card'},h('label',{},'独立批准密钥（只用这一次）'),h('input',{id:'own',type:'password',autocomplete:'off'}),
   h('label',{},h('input',{id:'ok',type:'checkbox',style:'width:auto;margin-right:6px'}),'我已核对金额、费用、合约、期限和退出条件，接受可能全部损失'),
   h('div',{class:'btns',style:'margin-top:10px'},h('button',{onclick:()=>act(()=>{if(!$('ok').checked)throw Error('请先勾选确认');return api('proposals/'+p.id+'/approve',{digest:p.digest,owner_token:$('own').value});},'已批准')},'批准执行'),h('button',{class:'ghost',onclick:()=>act(()=>api('proposals/'+p.id+'/reject',{}),'已拒绝')},'拒绝'))):null);}

let FILTER='go',SORT='composite',MAXMIN='',MAXCAP='',MODE='list';const OPEN=new Set();
const SORTS=[['composite','综合'],['ev','期望金额'],['roi','收益率'],['minutes','人工时间'],['principal','本金']];
const sorter={composite:(a,b)=>((b.composite??-1)-(a.composite??-1))||((b.certainty||0)-(a.certainty||0)),ev:(a,b)=>((b.ev_usd??-1e9)-(a.ev_usd??-1e9))||((b.certainty||0)-(a.certainty||0)),
 roi:(a,b)=>((b.roi??(b.principal_usd?-1e9:1e9))-(a.roi??(a.principal_usd?-1e9:1e9))),minutes:(a,b)=>((a.human_minutes??1e9)-(b.human_minutes??1e9))||((b.ev_usd??0)-(a.ev_usd??0)),principal:(a,b)=>((a.principal_usd??0)-(b.principal_usd??0))||((b.ev_usd??0)-(a.ev_usd??0))};
function meta(r){const x=[];x.push(r.principal_usd?'本金 '+usd(r.principal_usd):'无需本金');if(r.human_minutes!=null)x.push(r.human_minutes+' 分钟');if(r.roi!=null)x.push('收益率 '+(r.roi*100).toFixed(1)+'%');if(r.composite!=null)x.push('综合 '+Math.round(r.composite));return x.join(' · ');}
function line(r){return h('a',{href:'#act/'+encodeURIComponent(r.id),class:'row',style:'color:inherit;text-decoration:none'},h('div',{class:'t'},h('div',{},(r.priority?'★'+r.priority+' ':'')+r.title),h('small',{},meta(r)),h('div',{},status(r.status))),evSpan(r.ev_usd));}
function sel(id,val,opts,on){return h('select',{id,style:'width:auto;padding:7px 10px;font-size:14px',onchange:e=>on(e.target.value)},opts.map(([v,l])=>h('option',{value:v,selected:v===val},l)));}
async function acts(){const d=(await load(['strategy'])).strategy;const W=(BOOT.settings.effective.category_priors)||{};
 const want=r=>{if((W[r.category]||{}).weight===0)return FILTER==='out';
  const ok=FILTER==='all'?!r.skipped:FILTER==='go'?(!r.skipped&&r.ev_usd!=null&&r.ev_usd>0&&r.status!=='screened_out'):FILTER==='research'?(!r.skipped&&r.status!=='screened_out'&&!(r.ev_usd>0)):(r.skipped||r.status==='screened_out');
  return ok&&(MAXMIN===''||(r.human_minutes??0)<=+MAXMIN)&&(MAXCAP===''||(r.principal_usd??0)<=+MAXCAP);};
 const R=d.ranking.filter(want).sort(sorter[SORT]);
 const chips=[['go','可参加'],['research','研究中'],['all','全部'],['out','已筛掉/跳过']].map(([k,l])=>h('button',{class:'chip'+(FILTER===k?' cur':''),onclick:()=>{FILTER=k;acts();}},l));
 const sorts=SORTS.map(([k,l])=>h('button',{class:'chip'+(SORT===k?' cur':''),onclick:()=>{SORT=k;acts();}},l));
 const bar=h('div',{class:'chips'},sel('mm',MAXMIN,[['','人工不限'],['5','≤5 分钟'],['15','≤15 分钟'],['30','≤30 分钟'],['60','≤60 分钟']],v=>{MAXMIN=v;acts();}),
  sel('mc',MAXCAP,[['','本金不限'],['0','无需本金'],['50','≤50U'],['100','≤100U'],['500','≤500U']],v=>{MAXCAP=v;acts();}),
  h('button',{class:'chip',onclick:()=>{MODE=MODE==='list'?'cat':'list';acts();}},MODE==='list'?'按分类看':'按排行看'));
 let body;
 if(MODE==='list')body=h('div',{class:'card'},R.length?R.slice(0,60).map(line):h('div',{class:'muted'},'这个筛选下没有活动'));
 else{const g={};for(const r of R)(g[r.category]=g[r.category]||[]).push(r);
  body=Object.entries(g).map(([c,rs])=>{const best=Math.max(...rs.map(x=>x.ev_usd??-1e9));const el=h('details',{open:OPEN.has(c)},h('summary',{},h('span',{},(CAT[c]||c)+' · '+rs.length+' 个'),h('span',{class:'muted'},best>-1e9?'最高 '+usd(best):'')),h('div',{class:'in'},rs.slice(0,40).map(line)));el.addEventListener('toggle',()=>el.open?OPEN.add(c):OPEN.delete(c));return el;});
  if(!body.length)body=h('div',{class:'card muted'},'这个筛选下没有活动');}
 view(h('div',{class:'chips'},chips),h('div',{class:'chips'},sorts),bar,h('div',{class:'muted',style:'margin:4px 2px'},'共 '+R.length+' 个 · 综合 = 40% 金额 + 35% 每小时收益 + 25% 资金收益率（按排名）'),body);}

async function activity(id){const a=await api('activities/'+encodeURIComponent(id));const ev=a.ev||{};let pr=a.priority;
 const reasons=[...((a.screening||{}).reasons||[]),...(((a.screening||{}).handoff_blockers)||[])].filter((x,i,s)=>s.indexOf(x)===i&&x!=='eligible_for_analysis');
 const pv=h('span',{},pr);const step=d=>{pr=Math.max(-100,Math.min(100,pr+d));pv.textContent=pr;};
 const an=a.analysis||{};
 view(h('a',{href:'#acts'},'‹ 返回活动'),h('div',{class:'card'},h('h2',{style:'margin-top:0'},a.title),h('div',{class:'btns'},status(a.status),h('span',{class:'tag'},CAT[a.category]||a.category)),
  h('a',{class:'btn',style:'margin-top:10px;width:100%',href:a.url,target:'_blank',rel:'noopener noreferrer'},'打开官方页面')),
  h('div',{class:'card'},h('div',{class:'row'},h('div',{class:'t'},'期望收益'),evSpan(ev.ev_usd)),
   h('div',{class:'row'},h('div',{class:'t muted'},'得奖概率 × 奖励'),h('div',{},pct(ev.p_paid)+' × '+usd(ev.payout_usd))),
   h('div',{class:'row'},h('div',{class:'t muted'},'现金成本（Gas 等）/ AI'),h('div',{},usd(ev.cash_cost_usd)+' / '+usd(ev.ai_cost_usd))),
   h('div',{class:'row'},h('div',{class:'t muted'},'本金 / 人工'),h('div',{},(ev.principal_usd?usd(ev.principal_usd):'无需本金')+' / '+(ev.human_minutes!=null?ev.human_minutes+' 分钟':'未知'))),
   h('div',{class:'row'},h('div',{class:'t muted'},'收益率 / 每小时收益'),h('div',{},(ev.roi!=null?(ev.roi*100).toFixed(1)+'%':'—')+' / '+usd(ev.ev_per_hour_usd))),
   h('div',{class:'row'},h('div',{class:'t muted'},'数据可信度'),h('div',{},ev.certainty!=null?String(ev.certainty):'—')),
   h('div',{class:'muted',style:'margin-top:6px'},'依据：'+({stated_per_person_reward:'规则写明的每人奖励',pool_with_known_participants:'奖池 ÷ 预计人数',apr_snapshot:'年化快照 × 50% − Gas',category_prior:'分类默认估计',prior_blended_with_history:'分类估计 + 历史结果'}[ev.basis]||'还没算'))),
  reasons.length?h('details',{open:true},h('summary',{},'筛选原因（'+reasons.length+'）'),h('div',{class:'in'},reasons.map(x=>h('div',{class:'muted'},'· '+(REASON[x]||zh(x)))))):null,
  an.reason?h('details',{},h('summary',{},'AI 分析'),h('div',{class:'in'},h('div',{},an.reason),(an.risks||[]).map(x=>h('div',{class:'muted'},'风险：'+x)),(an.manual_steps||[]).length?h('ol',{},an.manual_steps.map(x=>h('li',{},x))):null)):null,
  h('div',{class:'card'},h('label',{},'优先级（越大越先处理）'),h('div',{class:'stepper'},h('button',{class:'ghost',onclick:()=>step(-1)},'−'),pv,h('button',{class:'ghost',onclick:()=>step(1)},'＋')),
   h('label',{},'结果'),h('select',{id:'oc'},[['','未知'],['paid','已到账'],['not_paid','未中/无奖励']].map(([v,l])=>h('option',{value:v,selected:(a.outcome||'')===v},l))),
   h('label',{},h('input',{id:'sk',type:'checkbox',checked:a.skipped,style:'width:auto;margin-right:6px'}),'跳过这个活动'),
   h('label',{},h('input',{id:'ie',type:'checkbox',checked:a.project_marked_ineligible,style:'width:auto;margin-right:6px'}),'账户不能参加（同类项目以后都跳过）'),
   h('button',{style:'margin-top:12px;width:100%',onclick:()=>act(()=>api('activities/'+encodeURIComponent(a.id),{priority:pr,skip:$('sk').checked,outcome:$('oc').value||null,ineligible:$('ie').checked}),'已保存')},'保存')),
  a.handoff?h('a',{class:'btn ghost',style:'width:100%',href:'#handoff/'+a.handoff.id},'查看任务交接单'):null);}

async function review(){const all=await load(['strategy','metrics']);const m=all.metrics;const d=all.strategy;
 view(h('div',{class:'grid'},h('div',{class:'stat'},h('small',{},'已实现净收益'),evSpan(micro(m.realized.realized_net_usd_micro))),h('div',{class:'stat'},h('small',{},'每人工小时净收益'),evSpan(micro(m.net_per_human_hour_usd_micro)))),
  h('h2',{},'按分类'),d.categories.filter(c=>c.discovered||c.finished).map(c=>h('details',{},h('summary',{},h('span',{},c.label),h('span',{class:'muted'},'净 '+usd(c.net_after_time_usd))),
   h('div',{class:'in'},[['发现 / 进行中 / 已完成',c.discovered+' / '+c.in_progress+' / '+c.finished],['中奖率',pct(c.win_rate)],['到账',usd(c.income_usd)],['现金成本',usd(c.cash_cost_usd)],['人工',c.human_minutes+' 分钟（'+usd(c.time_cost_usd)+'）'],['当前估计','概率 '+pct(c.current_p)+' · 奖励 '+usd(c.current_payout_usd)],['历史数据占比',pct(c.history_weight)]].map(([k,v])=>h('div',{class:'row'},h('div',{class:'t muted'},k),h('div',{},v)))))),
  h('div',{class:'muted',style:'margin:6px 2px'},'共享 AI 成本：'+usd(d.shared_ai_cost_usd)),
  h('details',{},h('summary',{},'登记到账'),h('div',{class:'in'},h('label',{},'活动（可选）'),h('select',{id:'io'},h('option',{value:''},'—'),d.ranking.slice(0,60).map(r=>h('option',{value:r.id},r.title.slice(0,40)))),
   h('label',{},'资产'),h('input',{id:'ia',placeholder:'USDC'}),h('label',{},'数量（按币显示，如 12.5）'),h('input',{id:'iq',inputmode:'decimal'}),h('label',{},'小数位'),h('input',{id:'idc',value:'6',inputmode:'numeric'}),h('label',{},'美元价值'),h('input',{id:'iu',inputmode:'decimal'}),
   h('label',{},'交易哈希 0x…（没有就填证据）'),h('input',{id:'it'}),h('button',{style:'margin-top:10px;width:100%',onclick:()=>act(()=>{const dec=parseInt($('idc').value,10);const raw=BigInt(Math.round(parseFloat($('iq').value)*10**Math.min(dec,6)))*10n**BigInt(Math.max(0,dec-6));const b={source_ref:$('io').value||'manual',asset:$('ia').value,amount_raw:raw.toString(),decimals:dec,usd_micro:Math.round(parseFloat($('iu').value)*1e6),price_basis:'spot_at_receipt'};if($('io').value)b.opportunity_id=$('io').value;const t=$('it').value.trim();if(/^0x[0-9a-fA-F]{64}$/.test(t))b.tx_hash=t;else b.evidence=t;return api('ledger/income',b);},'已登记到账')},'登记'))),
  h('details',{},h('summary',{},'登记费用'),h('div',{class:'in'},h('label',{},'类型'),h('select',{id:'cc'},['gas','trading','slippage','bridge','exit','claim','ai','hosting','other'].map(x=>h('option',{value:x},x))),h('label',{},'美元'),h('input',{id:'cu',inputmode:'decimal'}),h('label',{},'交易哈希或账单说明'),h('input',{id:'ct'}),
   h('button',{style:'margin-top:10px;width:100%',onclick:()=>act(()=>{const t=$('ct').value.trim();const b={category:$('cc').value,usd_micro:Math.round(parseFloat($('cu').value)*1e6)};if(/^0x[0-9a-fA-F]{64}$/.test(t))b.tx_hash=t;else b.evidence=t;return api('ledger/cost',b);},'已登记费用')},'登记'))));}

async function settingsView(){const d=await load(['settings','readiness','status']);const e=d.settings.effective;const ov={...d.settings.overrides};const pri=e.category_priors||{};
 const W={};const wv=c=>(pri[c]&&pri[c].weight!=null)?pri[c].weight:1;
 const rows=Object.entries(CAT).map(([c,l])=>{W[c]=wv(c);const sp=h('span',{},W[c].toFixed(1));const st=x=>{W[c]=Math.max(0,Math.min(10,Math.round((W[c]+x)*10)/10));sp.textContent=W[c].toFixed(1);};
  return h('div',{class:'row'},h('div',{class:'t'},l),h('div',{class:'stepper'},h('button',{class:'ghost',onclick:()=>st(-0.5)},'−'),sp,h('button',{class:'ghost',onclick:()=>st(0.5)},'＋')));});
 view(h('div',{class:'card'},h('label',{},'存款类活动的试算本金（美元）'),h('input',{id:'sp',inputmode:'decimal',value:(e.default_principal_usd_micro||50e6)/1e6}),
   h('label',{},'综合排序权重：金额 / 每小时收益 / 资金收益率'),h('div',{class:'btns'},['amount','hourly','capital'].map(k=>h('input',{id:'rw_'+k,inputmode:'decimal',value:(e.rank_weights||{})[k]??''}))),
   h('label',{},'最低期望收益（美元，低于不通知你）'),h('input',{id:'sm',inputmode:'decimal',value:e.min_net_usd_micro==null?'':e.min_net_usd_micro/1e6}),
   h('label',{},'钱包公开地址'),h('input',{id:'sa',value:e.receiver_address||'',placeholder:'0x…'})),
  h('h2',{},'分类开关（调到 0 = 不看这类活动）'),h('div',{class:'card'},rows),
  h('button',{style:'width:100%;margin-top:6px',onclick:()=>act(()=>{const n=(id,k)=>{const v=$(id).value.trim();if(v==='')delete ov[k];else ov[k]=Math.round(parseFloat(v)*1e6);};n('sp','default_principal_usd_micro');n('sm','min_net_usd_micro');
   const rw={};for(const k of ['amount','hourly','capital']){const v=parseFloat($('rw_'+k).value);if(!isNaN(v))rw[k]=v;}if(Object.keys(rw).length)ov.rank_weights=rw;
   const a=$('sa').value.trim();if(a){ov.receiver_address=a;ov.receiver_chain_id=ov.receiver_chain_id||1;ov.receiver_rpc_url=ov.receiver_rpc_url||'https://ethereum-rpc.publicnode.com';}else delete ov.receiver_address;
   const cp={...(ov.category_priors||{})};for(const c in W){if(W[c]!==1||(cp[c]&&cp[c].weight!=null))cp[c]={...(cp[c]||{}),weight:W[c]};}ov.category_priors=cp;return api('settings',{overrides:ov});},'设置已保存，下次运行生效')},'保存设置'),
  h('details',{},h('summary',{},'退出登录'),h('div',{class:'in'},h('button',{class:'ghost',style:'width:100%',onclick:()=>{TOKEN='';try{localStorage.removeItem('ac_token');localStorage.removeItem('ac_boot');}catch(x){}BOOT=null;route();}},'在这台设备上退出'))),
  h('details',{},h('summary',{},'开发者信息'),h('div',{class:'in'},h('pre',{},JSON.stringify({readiness:d.readiness,runtime:d.status.runtime,settings:d.settings},null,1)))));}

const ROUTES={home,todo,acts,review,set:settingsView};
async function route(){const hash=(location.hash||'#home').slice(1);const [name,arg]=hash.split('/');
 for(const a of document.querySelectorAll('nav a'))a.classList.toggle('cur',a.dataset.t===(name==='act'?'acts':name==='handoff'||name==='proposal'?'todo':name));
 if(!TOKEN)return login();
 try{if(name==='act')await activity(decodeURIComponent(arg));else if(name==='handoff')await handoff(arg);else if(name==='proposal')await proposal(arg);else await (ROUTES[name]||home)();}
 catch(e){toast(e.message);if(!TOKEN)login();}}
window.addEventListener('hashchange',route);route();
</script></body></html>'''
