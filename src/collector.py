"""Collect official listings; external text is evidence, never an instruction."""
import re
from html.parser import HTMLParser
from urllib.parse import urljoin
from common import Blocked, canonical, digest, now
from network import request, get_json

BINANCE_LIST = "https://www.binance.com/en/support/announcement/new-cryptocurrency-listing?c=48&navId=48"
MERKL_LIST = "https://api.merkl.xyz/v4/opportunities"
# Public CMS listing used by Binance's own announcement pages (48 = new listings, 93 = latest activities).
BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=20&catalogId="
BINANCE_CATALOGS = (48, 93)
BINANCE_KEYWORDS = re.compile(r"launchpool|hodler airdrop|megadrop|airdrop|launchpad", re.I)


def binance_articles(value):
    """Validate the CMS JSON shape and return (url,title,release_ms). Unknown shape is an error, not empty."""
    if not isinstance(value, dict) or value.get("success") is not True:
        raise Blocked("binance_schema_changed")
    catalogs = (value.get("data") or {}).get("catalogs")
    if not isinstance(catalogs, list) or not catalogs or not isinstance(catalogs[0].get("articles"), list):
        raise Blocked("binance_schema_changed")
    out = []
    for a in catalogs[0]["articles"][:50]:
        code, title = a.get("code"), a.get("title")
        if isinstance(code, str) and re.fullmatch(r"[0-9a-f]{32}", code) and isinstance(title, str):
            out.append(("https://www.binance.com/en/support/announcement/detail/" + code, title[:240], a.get("releaseDate")))
    return out


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
        status=CASE WHEN opportunities.fingerprint!=excluded.fingerprint OR opportunities.status='screened_out' THEN 'discovered' ELSE opportunities.status END""",
        c["id"],c["source"],c["title"],c["url"],c["fingerprint"],canonical(c["data"]),now())


async def discover(store, page=0, env=None):
    results = {}
    for source in ("galxe","binance","merkl"):
        try:
            candidates = []
            if source == "galxe":
                from galxe import discover as discover_tasks
                result = await discover_tasks(env, store, page)
                results[source] = result
                if result["state"] == "not_configured":
                    continue
                await store.run("INSERT INTO sources(id,last_ok,observed_count) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_ok=excluded.last_ok,last_error=NULL,observed_count=excluded.observed_count",source,now(),result["count"])
                continue
            if source == "binance":
                links = []
                try:
                    for catalog in BINANCE_CATALOGS:
                        links += binance_articles(await get_json(BINANCE_CMS + str(catalog), max_bytes=400000))
                except Blocked:
                    # Fallback: static page links (often blocked for server IPs).
                    parser = Announcements()
                    parser.feed(await request(BINANCE_LIST, max_bytes=2_000_000))
                    if not parser.links:
                        raise Blocked("binance_listing_unreadable")
                    links = [(u, t, None) for u, t in parser.links]
                for url, title, released in {u: (u, t, r) for u, t, r in links}.values():
                    if not BINANCE_KEYWORDS.search(title):
                        continue
                    data = {"title":title,"official_url":url,"released_ms":released,
                            "execution":"unverified_official_subscription_api"}
                    rules = {k: v for k, v in data.items() if k != "released_ms"}
                    candidates.append({"id":"binance:"+url.rsplit("/",1)[1],"source":source,"title":title,
                                       "url":url,"fingerprint":digest(rules),"data":data})
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
