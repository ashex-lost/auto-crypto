import { DurableObject } from 'cloudflare:workers';
import { Executor } from './engine.js';
const json=(data,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store'}});
async function authorized(request,secret) {
  if(typeof secret!=='string'||secret.length<32||secret.length>256) return false;
  const supplied=request.headers.get('authorization')||'';
  if(supplied.length>300) return false;
  const a=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(supplied));
  const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode('Bearer '+secret));
  return crypto.subtle.timingSafeEqual(a,b);
}

export default {
  async fetch(request,env) {
    const path=new URL(request.url).pathname;
    const owner=path.startsWith('/owner/');
    if(!await authorized(request,owner?env.OWNER_TOKEN:env.EXECUTION_TOKEN)) return json({error:'unauthorized'},401);
    if(!['/preview','/advance','/state','/pause','/owner/check','/owner/resume','/owner/approve'].includes(path)) return json({error:'not_found'},404);
    return env.WALLET.get(env.WALLET.idFromName('only-wallet')).fetch(request);
  }
};

export class WalletExecutor extends DurableObject {
  constructor(ctx,env) { super(ctx,env);this.engine=new Executor(ctx.storage,env);this.tail=Promise.resolve(); }
  async fetch(request) {
    const task=this.tail.then(()=>this.engine.handle(request));this.tail=task.catch(()=>{});return task;
  }
}
