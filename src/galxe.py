"""Galxe official read-only adapter; no mutation, login or reward claim endpoint.

Contract: https://docs.galxe.com/galxe-integration/api-reference/quest
Access token required: https://docs.galxe.com/galxe-integration/getting-started/authentication
"""
import json
import re
from common import Blocked, address, canonical, campaign_timestamp, digest, now
from config import binding
from network import get_json

ENDPOINT = 'https://graphigo-business.prd.galaxy.eco/query'
LIST = '''query GetSpaceQuests($input: ListQuestInput!) {
  quests(input: $input) {
    pageInfo { hasNextPage endCursor }
    list { id name type status description startTime endTime cap participantsCount loyaltyPoints gasType }
  }
}'''
CHECK = '''query CheckQuestEligibility($questId: ID!, $address: String!) {
  quest(id: $questId) {
    id name status startTime endTime cap participantsCount
    credentialGroups(address: $address) {
      id name conditionRelation
      conditions { expression eligible }
      rewards { expression eligible rewardType rewardCount }
    }
  }
}'''


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise Blocked('galxe_invalid_id')
    return value


def spaces(env):
    try:
        ids = json.loads(str(binding(env, 'GALXE_SPACE_IDS_JSON', '[]')))
    except (ValueError, TypeError):
        raise Blocked('galxe_spaces_invalid') from None
    if not isinstance(ids, list) or len(ids) > 10 or len(set(map(str, ids))) != len(ids):
        raise Blocked('galxe_spaces_invalid')
    return [identifier(item) for item in ids]


def capabilities(env):
    try:
        ids = spaces(env)
        error = None
    except Blocked as e:
        ids, error = [], str(e)
    token = bool(binding(env, 'GALXE_ACCESS_TOKEN'))
    return {'id': 'galxe_read_v1', 'name': 'Galxe 任务活动',
            'can_read': token and bool(ids) and not error,
            'token_configured': token, 'watched_spaces': len(ids),
            'wallet_configured': bool(binding(env, 'RECEIVER_ADDRESS')),
            'can_execute': False, 'blocker': error or (None if token and ids else 'galxe_access_and_spaces_needed'),
            'note': '可自动读活动和查资格；尚未接入任务提交或领奖，资格满足不代表已参与或已到账。'}


async def query(env, document, variables):
    # Only compiled read queries reach this endpoint. No arbitrary GraphQL from model/user.
    if document not in (LIST, CHECK):
        raise Blocked('galxe_query_not_allowed')
    token = str(binding(env, 'GALXE_ACCESS_TOKEN'))
    if not token:
        raise Blocked('galxe_access_token_missing')
    value = await get_json(ENDPOINT, method='POST', timeout=12, max_bytes=120000,
        headers={'Content-Type': 'application/json', 'access-token': token},
        body={'query': document, 'variables': variables})
    if not isinstance(value, dict) or value.get('errors'):
        # Error text is untrusted and can contain credentials. Never persist it.
        raise Blocked('galxe_api_error')
    if not isinstance(value.get('data'), dict):
        raise Blocked('galxe_schema_changed')
    return value['data']


def availability(row, timestamp=None):
    t = now() if timestamp is None else timestamp
    reasons = []
    if row.get('status') != 'Active': reasons.append('task_not_active')
    start, end = campaign_timestamp(row.get('startTime')), campaign_timestamp(row.get('endTime'))
    if start is None or end is None: reasons.append('task_dates_unknown')
    elif start > t or end <= t: reasons.append('task_outside_window')
    cap, count = row.get('cap'), row.get('participantsCount')
    if type(cap) is not int or type(count) is not int or cap < 0 or count < 0:
        reasons.append('task_capacity_unknown')
    elif cap > 0 and count >= cap: reasons.append('task_full')
    return reasons


def candidate(row, space_id):
    if not isinstance(row, dict): raise Blocked('galxe_schema_changed')
    key = identifier(row.get('id'))
    name = row.get('name')
    if not isinstance(name, str) or not name: raise Blocked('galxe_schema_changed')
    url = 'https://app.galxe.com/quest/' + identifier(space_id) + '/' + key
    fields = ('type', 'status', 'startTime', 'endTime', 'cap', 'participantsCount', 'loyaltyPoints', 'gasType')
    source = {k: row.get(k) for k in fields}
    source['description'] = str(row.get('description') or '')[:6000]
    kind = {'Points': 'points', 'MysteryBox': 'raffle'}.get(row.get('type'), 'unannounced')
    data = {'adapter': 'galxe_read_v1', 'external_id': key, 'space_id': space_id,
            'official_url': url, 'name': name[:240], 'ends_at': source['endTime'],
            'reward_kind': kind, 'reward_per_person_usd_micro': None,
            'automation': 'unknown', 'eligibility': 'unknown',
            'requires_trading': None, 'requires_deposit': None, 'requires_public_post': None,
            'costs_usd_micro': {k: None for k in ('gas', 'trading', 'claim', 'ai', 'hosting', 'other')},
            'human_minutes': None, 'execution_supported': False, 'official': source}
    # Activity capacity is rechecked every tick; count fluctuations don't buy a fresh AI analysis.
    rules = {**data, 'official': {k:v for k,v in source.items() if k != 'participantsCount'}}
    return {'id': 'galxe:' + key, 'source': 'task', 'title': name[:240], 'url': url,
            'data': data, 'fingerprint': digest(rules)}


async def discover(env, store, page=0):
    ids = spaces(env)
    if not ids or not binding(env, 'GALXE_ACCESS_TOKEN'):
        return {'state': 'not_configured', 'count': 0}
    space_id = ids[page % len(ids)]
    previous = await store.one('SELECT cursor FROM adapter_cursors WHERE source=?', 'galxe:' + space_id)
    after = previous['cursor'] if previous else None
    value = await query(env, LIST, {'input': {'spaceId': space_id, 'statuses': ['Active'], 'first': 10, 'after': after}})
    listing = value.get('quests')
    if not isinstance(listing, dict) or not isinstance(listing.get('list'), list) or len(listing['list']) > 10:
        raise Blocked('galxe_schema_changed')
    info = listing.get('pageInfo')
    if not isinstance(info, dict) or type(info.get('hasNextPage')) is not bool:
        raise Blocked('galxe_schema_changed')
    cursor = info.get('endCursor') if info['hasNextPage'] else None
    if info['hasNextPage'] and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 1000 or cursor == after):
        raise Blocked('galxe_cursor_invalid')
    candidates = [candidate(row, space_id) for row in listing['list']]
    from collector import save_candidate
    for item in candidates: await save_candidate(store, item)
    # Advance only after the complete page is validated and saved; replay upserts are idempotent.
    await store.run('INSERT INTO adapter_cursors(source,cursor) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET cursor=excluded.cursor',
                    'galxe:' + space_id, cursor)
    return {'state': 'read', 'count': len(candidates)}


def qualification(row):
    groups = row.get('credentialGroups')
    if not isinstance(groups, list) or not groups: return 'unknown'
    outcomes = []
    for group in groups:
        if not isinstance(group, dict): return 'unknown'
        conditions, rewards = group.get('conditions'), group.get('rewards')
        if not isinstance(conditions, list) or not conditions or not isinstance(rewards, list) or not rewards:
            outcomes.append(None); continue
        if any(not isinstance(c, dict) or type(c.get('eligible')) is not bool for c in conditions + rewards):
            outcomes.append(None); continue
        values = [c['eligible'] for c in conditions]
        relation = group.get('conditionRelation')
        passed = all(values) if relation == 'ALL' else any(values) if relation == 'ANY' else None
        outcomes.append(None if passed is None else passed and any(r['eligible'] for r in rewards))
    return 'conditions_met' if True in outcomes else 'unknown' if None in outcomes else 'conditions_not_met'


async def check_eligibility(env, store, opportunity_id):
    row = await store.one('SELECT * FROM opportunities WHERE id=? AND source=\'task\'', opportunity_id)
    if not row: raise Blocked('galxe_opportunity_missing')
    data = json.loads(row['data'])
    if data.get('adapter') != 'galxe_read_v1': raise Blocked('galxe_opportunity_missing')
    if not binding(env, 'GALXE_ACCESS_TOKEN'): raise Blocked('galxe_access_token_missing')
    if data.get('space_id') not in spaces(env): raise Blocked('galxe_space_not_watched')
    wallet = address(str(binding(env, 'RECEIVER_ADDRESS')))
    key, t = identifier(data['external_id']), now()
    # Reserve the slot BEFORE network I/O. Concurrent clicks and uncertain errors can't create a tight loop.
    slot = await store.one('''INSERT INTO task_checks(opportunity_id,checked_at,status) VALUES(?,?,?)
        ON CONFLICT(opportunity_id) DO UPDATE SET checked_at=excluded.checked_at,status=excluded.status,result=NULL
        WHERE task_checks.checked_at<=? RETURNING opportunity_id''', opportunity_id,t,'checking',t-300)
    if not slot: raise Blocked('galxe_check_cooldown')
    try:
        result = await query(env, CHECK, {'questId': key, 'address': wallet})
        quest = result.get('quest')
        if not isinstance(quest, dict) or quest.get('id') != key: raise Blocked('galxe_schema_changed')
        reasons = availability(quest, t)
        observation = {'checked_at': t, 'address': wallet, 'availability_blockers': reasons,
                       'qualification': qualification(quest), 'participation_approved': False,
                       'claimed': False, 'income_usd_micro': None,
                       'note': '只读资格快照，不确认地区许可、领取成功或奖励到账。'}
        await store.run('UPDATE task_checks SET status=?,result=? WHERE opportunity_id=?',
                        'checked', canonical(observation), opportunity_id)
        return observation
    except Blocked as e:
        await store.run('UPDATE task_checks SET status=?,result=? WHERE opportunity_id=?',
                        'error', canonical({'error': str(e)}), opportunity_id)
        raise


async def check_next(env, store):
    if not binding(env, 'GALXE_ACCESS_TOKEN') or not binding(env, 'RECEIVER_ADDRESS'):
        return {"state":"not_configured"}
    # One read per discovery cycle; oldest observations first. It never creates an approval.
    rows = await store.all("""SELECT o.id,o.data FROM opportunities o
        LEFT JOIN task_checks t ON t.opportunity_id=o.id
        WHERE o.source='task' AND o.id LIKE 'galxe:%' AND o.observed_at>?
        AND COALESCE(t.checked_at,0)<? ORDER BY COALESCE(t.checked_at,0) LIMIT 20""",now()-86400,now()-3600)
    for row in rows:
        data=json.loads(row['data'])
        if data.get('space_id') in spaces(env) and not availability(data.get('official',{})):
            try:
                return await check_eligibility(env,store,row['id'])
            except Blocked as e:
                return {"state":"blocked","reason":str(e)}
    return {"state":"idle"}
