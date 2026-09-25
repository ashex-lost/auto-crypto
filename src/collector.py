"""Collect official listings; external text is evidence, never an instruction."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from common import Blocked, canonical, digest, now
from network import request, get_json

BINANCE_LIST = "https://www.binance.com/en/support/announcement/new-cryptocurrency-listing?c=48&navId=48"
MERKL_LIST = "https://api.merkl.xyz/v4/opportunities"


class Announcements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.href, self.words = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.words = []

    def handle_data(self, data):
        if self.href:
            self.words.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            title = " ".join(self.words).strip()
            url = urljoin(BINANCE_LIST, self.href)
            if re.fullmatch(r"https://www\.binance\.com/en/support/announcement/detail/[0-9a-f]{32}",url):
                self.links.append((url,title))
            self.href = None


def merkl_candidate(row):
    if not isinstance(row,dict) or not all(k in row for k in ("id","name","chainId","status")):
        raise Blocked("merkl_schema_changed")
    # Keep terms and identifiers; discard graphics and volatile point-in-time prices.
    fields = ("id","name","chainId","type","status","action","description","howToSteps",
              "explorerAddress","apr","earliestCampaignStart","earliestCampaignEnd","depositUrl","liveCampaigns")
    data = {k:row.get(k) for k in fields}
    data["rewards"] = [{"address":r.get("token",{}).get("address"),"symbol":r.get("token",{}).get("symbol"),
                        "campaign_id":r.get("campaignId")} for r in row.get("rewardsRecord",{}).get("breakdowns",[])][:20]
    data["tokens"] = [{k:t.get(k) for k in ("address","symbol","decimals")} for t in row.get("tokens",[])][:20]
    data["protocol"] = (row.get("protocol") or {}).get("id")
    # APR changes affect economics, but not the cached language/rules analysis.
    rules = {k:v for k,v in data.items() if k != "apr"}
    return {"id":"merkl:"+str(row["id"]),"source":"merkl","title":str(row["name"])[:240],
            "url":MERKL_LIST+"/"+str(row["id"]),"data":data,"fingerprint":digest(rules)}


async def save_candidate(store, c):
    await store.run("""INSERT INTO opportunities(id,source,title,url,fingerprint,data,observed_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,url=excluded.url,
        fingerprint=excluded.fingerprint,data=excluded.data,observed_at=excluded.observed_at,
        status=CASE WHEN opportunities.fingerprint!=excluded.fingerprint THEN 'discovered' ELSE opportunities.status END""",
        c["id"],c["source"],c["title"],c["url"],c["fingerprint"],canonical(c["data"]),now())


async def discover(store, page=0):
    results = {}
    for source in ("binance","merkl"):
        try:
            candidates = []
            if source == "binance":
                parser = Announcements()
                parser.feed(await request(BINANCE_LIST, max_bytes=2_000_000))
                if not parser.links:
                    raise Blocked("binance_listing_unreadable")
                for url,title in dict(parser.links).items():
                    if "launchpool" not in title.lower():
                        continue
                    data = {"title":title,"official_url":url,"execution":"unverified_official_subscription_api"}
                    candidates.append({"id":"binance:"+url.rsplit("/",1)[1],"source":source,"title":title,
                                       "url":url,"fingerprint":digest(data),"data":data})
            else:
                data = await get_json(MERKL_LIST+f"?items=10&page={page}",max_bytes=600000)
                if not isinstance(data,list):
                    raise Blocked("merkl_schema_changed")
                candidates = [merkl_candidate(row) for row in data if row.get("status")=="LIVE"]
            for candidate in candidates[:10]:
                await save_candidate(store,candidate)
            await store.run("INSERT INTO sources(id,last_ok,observed_count) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_ok=excluded.last_ok,last_error=NULL,observed_count=excluded.observed_count",source,now(),len(candidates))
            results[source] = {"count":len(candidates)}
        except Blocked as error:
            code = str(error)
            await store.run("INSERT INTO sources(id,last_error) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET last_error=excluded.last_error",source,code)
            await store.event("source:"+source+":"+code,"source_error",{"source":source,"code":code})
            results[source] = {"error":code}
    return results


async def refresh_merkl(store, opportunity_id):
    external_id=opportunity_id.removeprefix("merkl:")
    if not re.fullmatch(r"[0-9]{1,30}",external_id):
        raise Blocked("invalid_opportunity_id")
    raw=await get_json(MERKL_LIST+"/"+external_id,max_bytes=150000)
    c=merkl_candidate(raw)
    if c["id"]!=opportunity_id:
        raise Blocked("source_id_mismatch")
    await save_candidate(store,c)
    return c
