"""Persistent notification outbox; dashboard always works, Telegram is optional."""
import json
from common import Blocked, now
from config import binding
from network import get_json


async def deliver(env,store):
    token=str(binding(env,"TELEGRAM_BOT_TOKEN")); chat=str(binding(env,"TELEGRAM_CHAT_ID"))
    if not token or not chat:
        return "dashboard_only"
    row=await store.one("SELECT * FROM events WHERE delivered_at IS NULL AND next_attempt<=? ORDER BY created_at LIMIT 1",now())
    if not row:
        return "idle"
    attempts=row["attempts"]+1
    await store.run("UPDATE events SET attempts=?,next_attempt=? WHERE id=?",attempts,now()+min(86400,60*2**min(attempts,10)),row["id"])
    # No address, balance, API token or transaction payload is included in the push message.
    text="Auto Crypto："+row["kind"]+"。请打开你的控制台查看。事件编号："+row["id"][:64]
    try:
        result=await get_json("https://api.telegram.org/bot"+token+"/sendMessage",method="POST",
                              body={"chat_id":chat,"text":text,"disable_web_page_preview":True},
                              headers={"Content-Type":"application/json"},timeout=8)
        if result.get("ok") is not True:
            raise Blocked("notification_failed")
        await store.run("UPDATE events SET delivered_at=? WHERE id=?",now(),row["id"])
        return "sent"
    except Blocked:
        return "delivery_pending"  # At-least-once delivery; timeout can result in duplicate notifications.
