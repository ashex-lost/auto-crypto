"""Run only against a disposable local Worker, never a deployed/funded service."""
import json
from urllib.request import Request,urlopen
from urllib.error import HTTPError

BASE='http://localhost:8789'
TOKEN='local-runtime-test-token-not-for-deployment-12345'


def call(path,body=None,authenticated=True,extra=None):
    headers={'Content-Type':'application/json'}
    if authenticated:headers['Authorization']='Bearer '+TOKEN
    headers.update(extra or {})
    r=Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    try:
        with urlopen(r,timeout=55) as response:
            raw=response.read()
            try:data=json.loads(raw) if raw else {}
            except ValueError:data={'text':raw.decode()}
            return response.status,data
    except HTTPError as e:
        return e.code,json.loads(e.read())


if __name__=='__main__':
    assert call('/healthz',authenticated=False)[0]==200
    assert call('/api/status',authenticated=False)[0]==401
    assert call('/api/control',{'paused':False},extra={'Origin':'https://example.invalid'})[0]==403
    status,data=call('/api/status');assert status==200
    assert not data['runtime']['model_key_connected'] and data['runtime']['reviewed_adapters']==0
    assert data['proposals']==[], 'Use a clean local database without approved plans.'
    assert call('/api/control',{'paused':True})[1]['executor_paused'] is True
    assert call('/api/tick',{})[1]['state']=='paused'
    try:
        call('/api/control',{'paused':False})
        status,data=call('/api/tick',{});assert status==200,data
        print('Real Worker/D1 tick:',json.dumps(data,ensure_ascii=False))
        status,data=call('/api/status');assert status==200
        print('Source health:',json.dumps(data['runtime']['sources'],ensure_ascii=False))
        assert data['runtime']['last_tick'] is not None
    finally:
        call('/api/control',{'paused':True})
    status,data=call('/cdn-cgi/local/scheduled');assert status==200,data
    assert call('/api/status')[1]['runtime']['last_cron'] is not None
    print('Runtime smoke passed: auth, origin, D1, pause, scheduled handler. No model key or wallet configured.')
