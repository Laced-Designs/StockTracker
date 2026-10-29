from fastapi.testclient import TestClient
from api.main import create_app
from api.config import Settings

def test_api_auth_order_validation_and_ws():
    with TestClient(create_app(Settings(database_url='sqlite://',tick_seconds=3600))) as c:
        assert c.get('/api/health').json()['mode']=='demo'
        d=c.get('/api/market/AAPL').json();assert len(d['bars'])>=780 and d['prediction']['mode']=='demo'
        a=c.post('/api/accounts',json={'name':'Student','initial_tokens':10000}).json();id=a['account']['id'];key=a['access_key']
        assert c.get('/api/accounts/'+id).status_code==403
        h={'Authorization':'Bearer '+key}
        assert c.get('/api/accounts/'+id,headers=h).status_code==200
        o={'client_id':'test','symbol':'AAPL','quantity':'1','type':'limit','price':'100'}
        assert c.post('/api/accounts/'+id+'/orders',json=o,headers=h).status_code==201
        assert c.delete('/api/accounts/'+id+'/orders/test',headers=h).status_code==200
        assert c.post('/api/accounts/'+id+'/orders',json=o|{'client_id':'bad','quantity':'NaN'},headers=h).status_code==422
        with c.websocket_connect('/ws/market') as ws:assert ws.receive_json()['mode']=='demo'
        assert c.get('/api/market/UNKNOWN').status_code==404

def test_live_without_credentials_degrades_without_demo_data():
    with TestClient(create_app(Settings(database_url='sqlite://',mode='live',alpaca_key='',alpaca_secret='',tick_seconds=3600))) as c:
        health=c.get('/api/health').json();assert health['status']=='degraded' and health['mode']=='live'
        assert c.get('/api/market').json()['quotes']=={}
        d=c.get('/api/market/AAPL').json();assert d['bars']==[] and d['depth']['bids']==[]
        assert d['prediction']['status']=='insufficient_history'

def test_news_feed_preserves_demo_provenance_and_availability():
    with TestClient(create_app(Settings(database_url='sqlite://',tick_seconds=3600))) as c:
        data=c.get('/api/news').json()
        assert data['mode']=='demo' and len(data['news'])==18
        assert all(n['mode']=='demo' and n['available_at']>=n['published_at'] for n in data['news'])
