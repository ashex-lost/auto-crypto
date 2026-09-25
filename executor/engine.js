import { Wallet, Interface, keccak256 } from 'ethers';
import { requireThat, uint, address, validatePlan, publicState } from './policy.js';

const ERC20=new Interface(['function allowance(address,address) view returns(uint256)','function approve(address,uint256) returns(bool)','function balanceOf(address) view returns(uint256)','function decimals() view returns(uint8)','event Transfer(address indexed from,address indexed to,uint256 value)']);
const VAULT=new Interface(['function asset() view returns(address)','function previewDeposit(uint256) view returns(uint256)','function previewMint(uint256) view returns(uint256)','function previewRedeem(uint256) view returns(uint256)','function maxMint(address) view returns(uint256)','function maxRedeem(address) view returns(uint256)','function mint(uint256,address) returns(uint256)','function redeem(uint256,address,address) returns(uint256)','event Deposit(address indexed sender,address indexed owner,uint256 assets,uint256 shares)','event Withdraw(address indexed sender,address indexed receiver,address indexed owner,uint256 assets,uint256 shares)']);
const MERKL=new Interface(['function claimed(address,address) view returns(uint208,uint48,bytes32)','function claimWithRecipient(address[],address[],uint256[],bytes32[][],address[],bytes[])','event Claimed(address indexed user,address indexed token,uint256 amount)']);
const hex=n=>'0x'+BigInt(n).toString(16);
const json=(data,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store'}});
async function hash(text) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join(''); }
export class Executor {
  constructor(storage,env,clock=()=>Math.floor(Date.now()/1000),fetcher=fetch) { this.storage=storage;this.env=env;this.now=clock;this.fetch=fetcher; }
  config() {
    const c=JSON.parse(this.env.EXECUTOR_CONFIG_JSON||'{}');
    requireThat(Array.isArray(c.vaults)&&c.vaults.length<=10,'executor_config_missing');
    requireThat([1,56].includes(c.chain_id),'chain_unsupported');
    requireThat(Number.isSafeInteger(c.confirmations)&&c.confirmations>=3&&c.confirmations<=64,'confirmation_config');
    requireThat(Number.isSafeInteger(c.gas_limit)&&c.gas_limit>=21000&&c.gas_limit<=1000000,'gas_config');
    requireThat(Number.isSafeInteger(c.max_gas_usd_micro)&&c.max_gas_usd_micro>0,'gas_usd_quote_missing');
    uint(c.lifetime_fee_cap_wei); uint(c.max_gas_price_wei);
    return c;
  }
  wallet() { requireThat(this.env.WALLET_PRIVATE_KEY,'wallet_key_missing'); return new Wallet(this.env.WALLET_PRIVATE_KEY); }
  async rpc(method,params) {
    const url=new URL(this.env.RPC_URL); requireThat(url.protocol==='https:','rpc_https_required');
    const r=await this.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params}),signal:AbortSignal.timeout(12000),redirect:'manual'});
    requireThat(r.ok,'rpc_unavailable'); const value=await r.json();
    requireThat(!value.error && 'result' in value,'rpc_error'); return value.result;
  }
  async read(target,abi,name,args=[]) {
    const data=await this.rpc('eth_call',[{to:target,data:abi.encodeFunctionData(name,args)},'latest']);
    return abi.decodeFunctionResult(name,data);
  }
  async verify(v,config) {
    requireThat(Number(BigInt(await this.rpc('eth_chainId',[])))===config.chain_id,'rpc_wrong_chain');
    for(const k of ['asset','vault','distributor']) {
      const code=await this.rpc('eth_getCode',[v[k],'latest']);
      requireThat(code!=='0x' && keccak256(code)===v[k+'_code_hash'],'contract_code_changed');
    }
    requireThat(address((await this.read(v.vault,VAULT,'asset'))[0])===address(v.asset),'vault_asset_changed');
    requireThat(Number((await this.read(v.asset,ERC20,'decimals'))[0])===v.asset_decimals,'asset_decimals_changed');
  }
  async handle(request) {
    try {
      const path=new URL(request.url).pathname;
      requireThat(request.method===(path==='/state'?'GET':'POST'),'method_not_allowed');
      const text=request.method==='POST'?await request.text():'{}'; requireThat(text.length<=16384,'body_too_large');
      const body=JSON.parse(text);
      if(path==='/owner/check') return json({authorized:true});
      if(path==='/state') return json({paused:(await this.storage.get('paused'))!==false,plan:publicState(await this.storage.get('plan'))});
      if(path==='/pause') { await this.storage.put('paused',true); return json({paused:true}); }
      if(path==='/owner/resume') {
        this.config(); this.wallet();
        const s=await this.storage.get('plan');
        requireThat(s?.id===body.id,'not_approved');
        requireThat(!['closed','needs_attention'].includes(s.stage),'plan_not_resumable');
        await this.storage.put('paused',false); return json({paused:false,id:s.id});
      }
      const config=this.config(),wallet=this.wallet(),who=wallet.address.toLowerCase();
      if(path==='/preview') {
        requireThat(config.gas_usd_quote_expires_at>this.now(),'gas_usd_quote_expired');
        const v=config.vaults.find(v=>v.id===body.vault_id); requireThat(v?.reviewed,'vault_not_reviewed');
        const amount=uint(body.amount_raw); requireThat(amount>0n&&amount<=uint(v.max_amount_raw),'principal_limit');
        await this.verify(v,config);
        const shares=(await this.read(v.vault,VAULT,'previewDeposit',[amount]))[0]*995n/1000n;
        requireThat(shares>0n,'zero_shares');
        requireThat((await this.read(v.vault,VAULT,'previewMint',[shares]))[0]<=amount,'mint_too_expensive');
        const balance=(await this.read(v.asset,ERC20,'balanceOf',[who]))[0];
        const allowance=(await this.read(v.asset,ERC20,'allowance',[who,v.vault]))[0];
        const fees=BigInt(7*config.gas_limit)*uint(config.max_gas_price_wei);
        requireThat(fees<=uint(config.lifetime_fee_cap_wei),'fee_limit');
        const native=BigInt(await this.rpc('eth_getBalance',[who,'latest']));
        return json({ready:balance>=amount&&native>=fees&&allowance===0n,wallet:who,distributor:address(v.distributor),asset_decimals:v.asset_decimals,
          shares_raw:shares.toString(),gas_limit:config.gas_limit,max_gas_price_wei:config.max_gas_price_wei,
          max_fee_wei:fees.toString(),max_gas_usd_micro:config.max_gas_usd_micro,
          checked_at:this.now(),simulation:'ERC4626 read-only previews; each actual transaction is eth_call tested before signing',
          requirements:{asset_balance:balance>=amount,gas_balance:native>=fees,zero_allowance:allowance===0n}});
      }
      if(path==='/owner/approve') {
        requireThat(config.gas_usd_quote_expires_at>this.now(),'gas_usd_quote_expired');
        requireThat(typeof body.canonical==='string','canonical_required');
        const p=JSON.parse(body.canonical),id=await hash(body.canonical);
        const previous=await this.storage.get('plan');
        if(previous?.id===id) return json(publicState(previous));
        const v=validatePlan(p,config,who,this.now());
        requireThat(!previous||previous.stage==='closed','one_active_plan_limit');
        requireThat(!await this.storage.get('used:'+id),'plan_already_used');
        await this.verify(v,config);
        requireThat((await this.read(v.asset,ERC20,'allowance',[who,v.vault]))[0]===0n,'existing_allowance');
        requireThat((await this.read(v.vault,ERC20,'balanceOf',[who]))[0]===0n,'existing_vault_position');
        const used=BigInt(await this.storage.get('fee_used')||'0');
        requireThat(used+uint(p.max_fee_wei)<=uint(config.lifetime_fee_cap_wei),'lifetime_fee_limit');
        const state={id,plan:p,stage:'approved',approved_at:this.now(),tx_count:0,claim_count:0,
          fee_wei:'0',deposited_raw:'0',shares_raw:'0',redeemed_raw:'0',claimed_raw:'0',pending:null,receipts:[]};
        await this.storage.put({'plan':state,['used:'+id]:true});
        return json(publicState(state));
      }
      requireThat(path==='/advance','not_found');
      const s=await this.storage.get('plan'); requireThat(s?.id===body.id,'not_approved');
      if(s.pending) { await this.reconcile(s,config); return json(publicState(s)); }
      if(s.stage==='closed'||s.stage==='needs_attention') return json(publicState(s));
      requireThat((await this.storage.get('paused'))===false,'executor_paused');
      const p=s.plan,v=config.vaults.find(v=>v.id===p.vault_id); requireThat(v?.reviewed,'vault_not_reviewed');
      for(const key of ['asset','vault','distributor']) requireThat(address(v[key])===address(p[key]),'approved_contract_changed');
      requireThat(config.chain_id===p.chain_id,'approved_chain_changed');
      await this.verify(v,config);
      if(s.stage==='approved') {
        if(this.now()>=p.expires_at) { s.stage='closed';await this.storage.put('plan',s);return json(publicState(s)); }
        await this.send(s,v.asset,ERC20,'approve',[v.vault,uint(p.amount_raw)],'approve',config);
      } else if(s.stage==='allowance_set') {
        // Approval may have mined just as entry expired; revoke instead of making a late investment.
        if(this.now()>=p.expires_at) await this.send(s,v.asset,ERC20,'approve',[v.vault,0n],'revoke_abort',config);
        else {
          requireThat((await this.read(v.asset,ERC20,'allowance',[who,v.vault]))[0]===uint(p.amount_raw),'allowance_changed');
          requireThat((await this.read(v.vault,VAULT,'previewMint',[uint(p.shares_raw)]))[0]<=uint(p.amount_raw),'entry_quote_changed');
          requireThat((await this.read(v.vault,VAULT,'maxMint',[who]))[0]>=uint(p.shares_raw),'mint_unavailable');
          await this.send(s,v.vault,VAULT,'mint',[uint(p.shares_raw),who],'mint',config);
        }
      } else if(s.stage==='deposited') {
        await this.send(s,v.asset,ERC20,'approve',[v.vault,0n],'revoke',config);
      } else if(s.stage==='holding') {
        const quote=(await this.read(v.vault,VAULT,'previewRedeem',[uint(s.shares_raw)]))[0];
        if(this.now()>=p.exit_at || quote*10000n<uint(s.deposited_raw)*BigInt(10000-p.stop_loss_bps)) {
          requireThat((await this.read(v.vault,VAULT,'maxRedeem',[who]))[0]>=uint(s.shares_raw),'exit_liquidity_unavailable');
          await this.send(s,v.vault,VAULT,'redeem',[uint(s.shares_raw),who,who],'redeem',config);
        } else if(s.claim_count<1) await this.claim(s,v,who,config);
      } else if(s.stage==='exited') {
        if(this.now()>p.claim_until||s.claim_count>=p.max_claims) { s.stage='closed'; await this.storage.put('plan',s); }
        else await this.claim(s,v,who,config);
      }
      return json(publicState(s));
    } catch(error) {
      // Never serialize ethers/fetch error objects: they can contain RPC credentials or raw transactions.
      const safe=/^[a-z][a-z0-9_]{2,80}$/.test(error.message)?error.message:'executor_internal_error';
      return json({error:safe},409);
    }
  }
  async claim(s,v,who,config) {
    const r=await this.fetch(`https://api.merkl.xyz/v4/users/${who}/rewards/summary?chainId=${config.chain_id}`,{signal:AbortSignal.timeout(10000),redirect:'manual'});
    requireThat(r.ok,'reward_api_unavailable'); const rows=await r.json(); requireThat(Array.isArray(rows),'reward_schema_changed');
    const rewards=rows.filter(x=>x.chain?.id===config.chain_id).flatMap(x=>x.rewards||[]);
    const item=rewards.find(x=>address(x.token?.address)===address(v.asset)); if(!item) return;
    const amount=uint(item.amount),claimed=(await this.read(v.distributor,MERKL,'claimed',[who,v.asset]))[0];
    if(amount<=claimed||amount-claimed<uint(s.plan.min_claim_raw)) return;
    requireThat(Array.isArray(item.proofs)&&item.proofs.length<=64&&item.proofs.every(x=>/^0x[0-9a-fA-F]{64}$/.test(x)),'invalid_proof');
    await this.send(s,v.distributor,MERKL,'claimWithRecipient',[[who],[v.asset],[amount],[item.proofs],[who],['0x']],'claim',config);
  }
  async send(s,to,abi,method,args,kind,config) {
    requireThat(s.tx_count<s.plan.max_txs,'transaction_limit');
    const wallet=this.wallet(),from=wallet.address.toLowerCase(),p=s.plan;
    const price=BigInt(await this.rpc('eth_gasPrice',[])); requireThat(price>0n&&price<=uint(p.max_gas_price_wei),'gas_price_above_cap');
    const call={from,to,data:abi.encodeFunctionData(method,args),value:'0x0'};
    await this.rpc('eth_call',[call,'latest']);
    const gas=BigInt(await this.rpc('eth_estimateGas',[call]))*120n/100n;
    requireThat(gas<=BigInt(p.gas_limit),'gas_above_cap');
    const reserved=gas*price;
    requireThat(uint(s.fee_wei)+reserved<=uint(p.max_fee_wei),'plan_fee_limit');
    const nonce=Number(BigInt(await this.rpc('eth_getTransactionCount',[from,'pending'])));
    const latest=Number(BigInt(await this.rpc('eth_getTransactionCount',[from,'latest'])));
    requireThat(nonce===latest,'external_pending_transaction');
    const raw=await wallet.signTransaction({type:0,chainId:p.chain_id,nonce,to,data:call.data,value:0n,gasLimit:gas,gasPrice:price});
    s.pending={raw,hash:keccak256(raw),kind,nonce,created_at:this.now(),reserved_fee:reserved.toString(),previous_stage:s.stage,broadcasts:1};
    s.tx_count++;
    // Persist signed bytes and hash FIRST. Recovery sends the same bytes, never a replacement nonce.
    await this.storage.put('plan',s);
    try { requireThat(await this.rpc('eth_sendRawTransaction',[raw])===s.pending.hash,'hash_mismatch'); } catch { /* Reconcile the stored hash on the next invocation. */ }
  }
  async reconcile(s,config) {
    const pending=s.pending,receipt=await this.rpc('eth_getTransactionReceipt',[pending.hash]);
    if(!receipt) {
      if(this.now()-pending.created_at>60 && pending.broadcasts<3) {
        pending.broadcasts++; await this.storage.put('plan',s);
        try { await this.rpc('eth_sendRawTransaction',[pending.raw]); } catch { /* Already known / uncertain; keep pending. */ }
      }
      if(this.now()-pending.created_at>900) s.attention='transaction_unconfirmed';
      await this.storage.put('plan',s); return;
    }
    requireThat(receipt.transactionHash.toLowerCase()===pending.hash.toLowerCase(),'receipt_hash_mismatch');
    const height=BigInt(await this.rpc('eth_blockNumber',[]));
    if(height-BigInt(receipt.blockNumber)+1n<BigInt(config.confirmations)) return;
    const block=await this.rpc('eth_getBlockByNumber',[receipt.blockNumber,false]);
    requireThat(block.hash===receipt.blockHash,'receipt_reorg');
    const fee=BigInt(receipt.gasUsed)*BigInt(receipt.effectiveGasPrice);
    const feeUsed=BigInt(await this.storage.get('fee_used')||'0')+fee;
    s.fee_wei=(uint(s.fee_wei)+fee).toString();
    const ok=BigInt(receipt.status)===1n;
    const record={hash:pending.hash,kind:pending.kind,block:receipt.blockNumber,fee_wei:fee.toString(),success:ok,at:this.now()};
    if(ok) {
      const p=s.plan,who=p.wallet;
      const events=receipt.logs.map(log=>{
        try {
          const iface=address(log.address)===address(p.vault)?VAULT:address(log.address)===address(p.distributor)?MERKL:null;
          return iface?.parseLog(log);
        } catch { return null; }
      }).filter(Boolean);
      if(pending.kind==='approve') s.stage='allowance_set';
      else if(pending.kind==='mint') {
        const e=events.find(e=>e.name==='Deposit'&&address(e.args.owner)===who);
        requireThat(e && e.args.assets<=uint(p.amount_raw)&&e.args.shares===uint(p.shares_raw),'deposit_receipt_mismatch');
        s.deposited_raw=e.args.assets.toString();s.shares_raw=e.args.shares.toString();s.stage='deposited';
      } else if(pending.kind==='revoke') s.stage='holding';
      else if(pending.kind==='revoke_abort') s.stage='closed';
      else if(pending.kind==='redeem') {
        const e=events.find(e=>e.name==='Withdraw'&&address(e.args.owner)===who&&address(e.args.receiver)===who);
        requireThat(e && e.args.shares===uint(s.shares_raw),'withdraw_receipt_mismatch');
        s.redeemed_raw=e.args.assets.toString();s.stage='exited';
      } else if(pending.kind==='claim') {
        const e=events.find(e=>e.name==='Claimed'&&address(e.args.user)===who&&address(e.args.token)===p.asset);
        requireThat(e,'claim_receipt_mismatch');
        // Only actual transfers to the wallet count as received; cumulative Merkl amounts do not.
        let received=0n;
        for(const log of receipt.logs) if(address(log.address)===p.asset) {
          try {const e=ERC20.parseLog(log);if(e?.name==='Transfer'&&address(e.args.to)===who&&address(e.args.from)===p.distributor) received+=e.args.value;} catch {}
        }
        requireThat(received>0n,'claim_transfer_missing');
        s.claimed_raw=(uint(s.claimed_raw)+received).toString();s.claim_count++;
      }
    } else { s.stage='needs_attention';s.attention='transaction_reverted'; }
    s.receipts.push(record);s.pending=null;
    await this.storage.put({'plan':s,'fee_used':feeUsed.toString()});
  }
}
