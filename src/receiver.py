"""Read-only wallet receiver: public balances only, never a signing key."""
import json
from common import Blocked, address
from config import binding
from network import get_json

BALANCE_OF="0x70a08231"
DECIMALS="0x313ce567"

def _hex(value):
    if not isinstance(value,str) or not value.startswith("0x"):
        raise Blocked("receiver_rpc_invalid_result")
    try:
        return int(value,16)
    except ValueError:
        raise Blocked("receiver_rpc_invalid_result") from None

def _assets(env):
    raw=str(binding(env,"RECEIVER_ASSETS_JSON","[]"))
    try: items=json.loads(raw)
    except ValueError:
        raise Blocked("receiver_assets_invalid") from None
    if not isinstance(items,list) or len(items)>20:
        raise Blocked("receiver_assets_invalid")
    result=[]
    for item in items:
        if not isinstance(item,dict):
            raise Blocked("receiver_assets_invalid")
        result.append({"address":address(item.get("address")),"symbol":str(item.get("symbol") or "asset")[:32],
                       "decimals":int(item.get("decimals",18))})
    return result

def configuration(env,s=None):
    s=s or {}
    raw=s.get("receiver_address") or binding(env,"RECEIVER_ADDRESS")
    receiver=address(str(raw)) if raw else ""
    rpc=str(s.get("receiver_rpc_url") or binding(env,"RECEIVER_RPC_URL"))
    chain=str(s.get("receiver_chain_id") or binding(env,"RECEIVER_CHAIN_ID",""))
    if not receiver or not rpc or not chain:
        return {"configured":False,"address":receiver or None,"chain_id":int(chain) if chain.isdigit() else None}
    if not rpc.startswith("https://"):
        raise Blocked("receiver_rpc_https_required")
    try: chain_id=int(chain)
    except ValueError:
        raise Blocked("receiver_chain_invalid") from None
    if chain_id not in (1,56):
        raise Blocked("receiver_chain_unsupported")
    return {"configured":True,"address":receiver,"chain_id":chain_id,"assets":_assets(env)}

async def snapshot(env,s=None):
    cfg=configuration(env,s)
    if not cfg["configured"]:
        return {"status":"not_configured","address":cfg.get("address"),"chain_id":cfg.get("chain_id")}
    rpc=str((s or {}).get("receiver_rpc_url") or binding(env,"RECEIVER_RPC_URL")); address_value=cfg["address"]
    def call(method,params):
        return get_json(rpc,method="POST",body={"jsonrpc":"2.0","id":1,"method":method,"params":params},
                        headers={"Content-Type":"application/json"},timeout=12)
    chain_result=await call("eth_chainId",[])
    chain_id=_hex(chain_result.get("result"))
    if chain_id!=cfg["chain_id"]:
        raise Blocked("receiver_chain_mismatch")
    native=await call("eth_getBalance",[address_value,"latest"])
    assets=[]
    padded=address_value[2:].lower().rjust(64,"0")
    for item in cfg["assets"]:
        result=await call("eth_call",[{"to":item["address"],"data":BALANCE_OF+padded},"latest"])
        assets.append({**item,"raw":str(_hex(result.get("result")))})
    return {"status":"ok","address":address_value,"chain_id":chain_id,
            "native_raw":str(_hex(native.get("result"))),"assets":assets}
