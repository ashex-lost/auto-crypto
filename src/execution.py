"""Client for a separate signing Worker. This Worker never receives a private key."""
from common import Blocked, canonical
from config import binding
from network import get_json


async def executor(env,path,body=None,owner_token=None):
    service = binding(env,"EXECUTOR",None)
    if service is None:
        raise Blocked("executor_not_connected")
    token = owner_token if owner_token is not None else str(binding(env,"EXECUTION_TOKEN"))
    if len(token)<32:
        raise Blocked("executor_token_missing")
    return await get_json("https://executor.internal"+path,method="POST" if body is not None else "GET",
                          body=body,headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
                          fetcher=service.fetch,timeout=25,max_bytes=120000)


async def approve(env,plan,owner_token):
    # Owner token is supplied for this request only, never persisted or passed to the model.
    return await executor(env,"/owner/approve",{"canonical":canonical(plan)},owner_token)


async def advance(env,plan_id):
    return await executor(env,"/advance",{"id":plan_id})
