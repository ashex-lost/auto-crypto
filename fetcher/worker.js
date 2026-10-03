// Tiny read-only fetch relay pinned near Binance's servers (Tokyo). Only reachable through the
// main Worker's service binding (no public route) and only for an allowlist of public GET URLs.
const ALLOW = [/^https:\/\/www\.binance\.com\/bapi\/composite\/v1\/public\/cms\/article\/list\/query\?[A-Za-z0-9=&]+$/,
               /^https:\/\/www\.binance\.com\/en\/support\/announcement\/[A-Za-z0-9\-?=&]+$/];
export default {
  async fetch(request) {
    const target = new URL(request.url).searchParams.get('u') || '';
    if (request.method !== 'GET' || !ALLOW.some(r => r.test(target))) {
      return Response.json({ error: 'fetch_not_allowed' }, { status: 400 });
    }
    const upstream = await fetch(target, { headers: { 'Accept': 'application/json,text/html' }, redirect: 'manual' });
    const body = await upstream.text();
    return new Response(body.slice(0, 2_000_000), { status: upstream.status,
      headers: { 'Content-Type': upstream.headers.get('Content-Type') || 'text/plain' } });
  },
};
