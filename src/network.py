"""Bounded Cloudflare fetch. No arbitrary URLs supplied by model output."""
import asyncio
import json
import re
from urllib.parse import urlsplit
from common import Blocked, canonical


async def request(url, *, method="GET", headers=None, body=None, max_bytes=262144, timeout=20, fetcher=None):
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise Blocked("https_required")
    from workers import fetch
    from js import AbortSignal
    options = {"method":method,"headers":headers or {},"redirect":"manual",
               "signal":AbortSignal.timeout(timeout*1000)}
    if body is not None:
        options["body"] = canonical(body)
    async def perform():
        # Service bindings expose a Python SDK wrapper, not a raw JS fetch callback.
        response = await (fetcher(url, **options) if fetcher else fetch(url, **options))
        reader = response.body.getReader()
        chunks, size = [], 0
        try:
            while True:
                part = await reader.read()
                if part.done:
                    break
                chunk = bytes(part.value.to_py())
                size += len(chunk)
                if size > max_bytes:
                    raise Blocked("upstream_body_too_large")
                chunks.append(chunk)
        finally:
            await reader.cancel()
        text=b"".join(chunks).decode("utf-8")
        if not 200 <= response.status < 300:
            if u.hostname=='executor.internal':
                try:
                    code=json.loads(text).get('error','')
                    if isinstance(code,str) and re.fullmatch(r'[a-z][a-z0-9_]{2,80}',code):
                        raise Blocked(code)
                except (ValueError,AttributeError):
                    pass
            raise Blocked("upstream_http_"+str(response.status))
        return text
    try:
        return await asyncio.wait_for(perform(), timeout+2)
    except Blocked:
        raise
    except Exception as error:
        # Class and local source line only: never log exception text, request URLs or headers.
        import traceback
        frames=traceback.extract_tb(error.__traceback__)
        print('network_failure',type(error).__name__,frames[-1].lineno if frames else 0)
        raise Blocked("upstream_unavailable") from None


async def get_json(url, **kwargs):
    text = await request(url, **kwargs)
    try:
        return json.loads(text)
    except ValueError:
        raise Blocked("upstream_invalid_json") from None
