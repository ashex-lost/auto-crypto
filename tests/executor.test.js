import test from 'node:test';
import assert from 'node:assert/strict';
import { Wallet,Interface,Transaction,keccak256 } from 'ethers';
import { Executor } from '../executor/engine.js';
import { validatePlan,publicState } from '../executor/policy.js';

// Public dummy test key, never funded and never written to deployment configuration.
const KEY='0x'+'01'.repeat(32),WHO=new Wallet(KEY).address.toLowerCase();
const ASSET='0x'+'11'.repeat(20),VAULT='0x'+'22'.repeat(20),DIST='0x'+'33'.repeat(20);
const abi=new Interface(['function allowance(address,address) view returns(uint256)','function approve(address,uint256) returns(bool)','function balanceOf(address) view returns(uint256)','function decimals() view returns(uint8)','function asset() view returns(address)','function previewDeposit(uint256) view returns(uint256)','function previewMint(uint256) view returns(uint256)','function previewRedeem(uint256) view returns(uint256)','function maxMint(address) view returns(uint256)','function maxRedeem(address) view returns(uint256)','function mint(uint256,address) returns(uint256)','function redeem(uint256,address,address) returns(uint256)','function claimed(address,address) view returns(uint208,uint48,bytes32)','function claimWithRecipient(address[],address[],uint256[],bytes32[][],address[],bytes[])','event Deposit(address indexed sender,address indexed owner,uint256 assets,uint256 shares)','event Withdraw(address indexed sender,address indexed receiver,address indexed owner,uint256 assets,uint256 shares)','event Claimed(address indexed user,address indexed token,uint256 amount)','event Transfer(address indexed from,address indexed to,uint256 value)']);
class Memory { constructor(){this.data=new Map();}async get(k){return structuredClone(this.data.get(k));}async put(k,v){for(const [key,value] of typeof k==='object'?Object.entries(k):[[k,v]])this.data.set(key,structuredClone(value));} }
function fixture(){
  let clock=100000;const storage=new Memory(),receipts=new Map();let nonce=0,allowance=0n,shares=0n,claimed=0n,available=0n;const broadcasts=[];let loseResponse=false,revertNext=false;
  const v={id:'test',reviewed:true,opportunity_id:'1',asset:ASSET,vault:VAULT,distributor:DIST,asset_decimals:6,max_amount_raw:'1000000',asset_code_hash:keccak256('0x6000'),vault_code_hash:keccak256('0x6000'),distributor_code_hash:keccak256('0x6000')};
  const config={chain_id:1,vaults:[v],confirmations:3,gas_limit:100000,max_gas_price_wei:'5',lifetime_fee_cap_wei:'10000000',max_gas_usd_micro:100000,gas_usd_quote_expires_at:110000};
  const p={version:1,adapter:'erc4626_merkl_v1',vault_id:'test',opportunity_id:'merkl:1',evidence_hash:'a'.repeat(64),chain_id:1,wallet:WHO,asset:ASSET,vault:VAULT,distributor:DIST,amount_raw:'1000000',shares_raw:'995000',max_fee_wei:'3500000',gas_limit:100000,max_gas_price_wei:'5',created_at:clock,expires_at:clock+1800,exit_at:clock+86400,claim_until:clock+2*86400,max_claims:2,max_txs:7,min_claim_raw:'1',stop_loss_bps:100};
  function log(name,args,address){const e=abi.encodeEventLog(abi.getEvent(name),args);return {...e,address};}
  const rpc=async(method,params)=>{
    switch(method){
      case 'eth_chainId':return '0x1';case 'eth_getCode':return '0x6000';case 'eth_getBalance':return '0xffffffffff';
      case 'eth_gasPrice':return '0x2';case 'eth_estimateGas':return '0x7530';
      case 'eth_getTransactionCount':return '0x'+nonce.toString(16);
      case 'eth_blockNumber':return '0x64';case 'eth_getBlockByNumber':return {hash:'0x'+'44'.repeat(32)};
      case 'eth_getTransactionReceipt':return receipts.get(params[0])||null;
      case 'eth_call':{
        const tx=abi.parseTransaction({data:params[0].data});let values;
        switch(tx.name){
          case 'asset':values=[ASSET];break;case 'decimals':values=[6];break;
          case 'allowance':values=[allowance];break;case 'balanceOf':values=[params[0].to.toLowerCase()===VAULT?shares:10000000n];break;
          case 'previewDeposit':case 'previewMint':case 'previewRedeem':values=[tx.args[0]];break;
          case 'maxMint':values=[100000000n];break;case 'maxRedeem':values=[shares];break;
          case 'claimed':values=[claimed,0,'0x'+'00'.repeat(32)];break;
          case 'approve':values=[true];break;case 'mint':case 'redeem':values=[tx.args[0]];break;
          case 'claimWithRecipient':values=[];break;default:throw Error('unexpected_method');
        }
        return abi.encodeFunctionResult(tx.name,values);
      }
      case 'eth_sendRawTransaction':{
        const raw=params[0],hash=keccak256(raw);broadcasts.push(raw);
        if(!receipts.has(hash)){
          const tx=Transaction.from(raw),call=abi.parseTransaction({data:tx.data}),logs=[];
          assert.equal(tx.chainId,1n);assert.equal(tx.value,0n);assert.equal(tx.nonce,nonce);
          const failed=revertNext;revertNext=false;
          if(!failed)switch(call.name){
            case 'approve':allowance=call.args[1];break;
            case 'mint':shares=call.args[0];allowance-=shares;logs.push(log('Deposit',[WHO,WHO,shares,shares],VAULT));break;
            case 'redeem':logs.push(log('Withdraw',[WHO,WHO,WHO,shares,shares],VAULT));shares=0n;break;
            case 'claimWithRecipient':{
              assert.equal(call.args[4][0].toLowerCase(),WHO);assert.equal(call.args[5][0],'0x');
              const received=call.args[2][0]-claimed;claimed=call.args[2][0];logs.push(log('Claimed',[WHO,ASSET,claimed],DIST));logs.push(log('Transfer',[DIST,WHO,received],ASSET));break;
            }
          }
          nonce++;receipts.set(hash,{transactionHash:hash,blockNumber:'0x60',blockHash:'0x'+'44'.repeat(32),gasUsed:'0x7530',effectiveGasPrice:'0x2',status:failed?'0x0':'0x1',logs});
        }
        if(loseResponse){loseResponse=false;throw Error('network_timeout');}return hash;
      }
      default:throw Error('unexpected_rpc_'+method);
    }
  };
  const fetcher=async(url,options)=>{if(String(url).startsWith('https://api.merkl.xyz'))return Response.json([{chain:{id:1},rewards:available?[{token:{address:ASSET},amount:available.toString(),proofs:[]}]:[]}]);const q=JSON.parse(options.body);return Response.json({jsonrpc:'2.0',id:1,result:await rpc(q.method,q.params)});};
  const env={EXECUTOR_CONFIG_JSON:JSON.stringify(config),RPC_URL:'https://rpc.invalid',WALLET_PRIVATE_KEY:KEY};
  let engine=new Executor(storage,env,()=>clock,fetcher);
  async function request(path,body){return (await engine.handle(new Request('https://executor.internal'+path,{method:path==='/state'?'GET':'POST',body:path==='/state'?undefined:JSON.stringify(body||{}),headers:{'Content-Type':'application/json'}}))).json();}
  return {p,config,storage,env,broadcasts,request,setTime:t=>clock=t,setRewards:n=>available=n,lose:()=>loseResponse=true,revert:()=>revertNext=true,restart:()=>engine=new Executor(storage,env,()=>clock,fetcher)};
}
async function approved(f){const result=await f.request('/owner/approve',{canonical:JSON.stringify(f.p)});assert.ok(result.id,JSON.stringify(result));await f.request('/owner/resume',{id:result.id});return result.id;}
async function step(f,id){return f.request('/advance',{id});}
async function enter(f,id){for(let i=0;i<6;i++)await step(f,id);const state=await f.request('/state');assert.equal(state.plan.stage,'holding');return state;}

test('unapproved machine request never signs',async()=>{const f=fixture();assert.equal((await step(f,'x')).error,'not_approved');assert.equal(f.broadcasts.length,0);});
test('approval does not bypass initial pause',async()=>{const f=fixture(),r=await f.request('/owner/approve',{canonical:JSON.stringify(f.p)});assert.equal((await step(f,r.id)).error,'executor_paused');});
test('foreign recipient, arbitrary calldata, extra budget and expired approval rejected',()=>{const f=fixture();for(const p of [{...f.p,wallet:ASSET},{...f.p,data:'0x1234'},{...f.p,amount_raw:'1000001'},{...f.p,expires_at:99999}])assert.throws(()=>validatePlan(p,f.config,WHO,100000));});
test('approved plan executes exact allowance, mint, revoke, exit and actual rewards',async()=>{const f=fixture(),id=await approved(f);await enter(f,id);f.setTime(f.p.exit_at+1);await step(f,id);await step(f,id);f.setRewards(123n);await step(f,id);const r=await step(f,id);assert.equal(r.redeemed_raw,'995000');assert.equal(r.claimed_raw,'123');assert.equal(r.receipts.length,5);assert.equal(r.fee_wei,'300000');assert.equal(r.raw,undefined);assert.equal(r.pending,null);f.setTime(f.p.claim_until+1);assert.equal((await step(f,id)).stage,'closed');});
test('lost broadcast response then restart reconciles without duplicate signature',async()=>{const f=fixture(),id=await approved(f);f.lose();await step(f,id);assert.equal(f.broadcasts.length,1);f.restart();const r=await step(f,id);assert.equal(r.stage,'allowance_set');assert.equal(f.broadcasts.length,1);});
test('pause reconciles pending receipt but stops new spending',async()=>{const f=fixture(),id=await approved(f);await step(f,id);await f.request('/pause');assert.equal((await step(f,id)).stage,'allowance_set');assert.equal((await step(f,id)).error,'executor_paused');assert.equal(f.broadcasts.length,1);});
test('reverted transaction is charged and never automatically resubmitted',async()=>{const f=fixture(),id=await approved(f);f.revert();await step(f,id);let r=await step(f,id);assert.equal(r.stage,'needs_attention');assert.equal(r.fee_wei,'60000');await step(f,id);assert.equal(f.broadcasts.length,1);});
test('expired entry after approval transaction revokes without investing',async()=>{const f=fixture(),id=await approved(f);await step(f,id);await step(f,id);f.setTime(f.p.expires_at+1);await step(f,id);const r=await step(f,id);assert.equal(r.stage,'closed');assert.equal(r.deposited_raw,'0');assert.equal(f.broadcasts.length,2);});
test('changed registry contract cannot redirect approved execution',async()=>{const f=fixture(),id=await approved(f);const config=JSON.parse(f.env.EXECUTOR_CONFIG_JSON);config.vaults[0].vault=DIST;f.env.EXECUTOR_CONFIG_JSON=JSON.stringify(config);assert.equal((await step(f,id)).error,'approved_contract_changed');assert.equal(f.broadcasts.length,0);});
test('public state never exposes signed bytes',()=>{assert.equal(publicState({id:'x',pending:{raw:'secret',hash:'h',kind:'mint',nonce:2,created_at:1}}).pending.raw,undefined);});
test('expired unstarted plan closes without spending',async()=>{const f=fixture(),id=await approved(f);f.setTime(f.p.expires_at+1);assert.equal((await step(f,id)).stage,'closed');assert.equal(f.broadcasts.length,0);});

test('resume is bound to an already approved exact plan',async()=>{const f=fixture();assert.equal((await f.request('/owner/resume',{id:'unknown'})).error,'not_approved');const id=await approved(f);await f.request('/pause');assert.equal((await f.request('/owner/resume',{id:'different'})).error,'not_approved');assert.equal((await f.request('/state')).paused,true);assert.equal((await f.request('/owner/resume',{id})).paused,false);assert.equal(f.broadcasts.length,0);});
