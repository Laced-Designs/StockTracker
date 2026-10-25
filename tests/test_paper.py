from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from core.db import DuckDBStore
from core.config import Settings
from core.history import HistoryCatalog
from paper.models import Quote,OrderRequest
from paper.ledger import PaperExchange,money,units
from paper.challenge import ChallengeRunner,REQUESTED_AT
from paper.replay import HistoricalReplay
from paper.analytics import account_analytics
from api.main import create_app

T=datetime(2026,10,25,17,15,32,tzinfo=timezone.utc)

@pytest.fixture
def exchange():
    s=DuckDBStore(':memory:');clock=[T];e=PaperExchange(s,clock=lambda:clock[0])
    yield e,clock
    s.close()

def q(t,price='100',mode='live',source='coinbase_public'):
    return Quote(symbol='BTC-USD',source=source,market_time=t,observed_at=t,bid=price,ask=price,mode=mode)

def buy(id='buy1',budget='100',source='coinbase_public'):
    return OrderRequest(client_order_id=id,symbol='BTC-USD',source=source,side='buy',token_budget=budget)


def test_next_quote_fill_conservation_and_idempotence(exchange):
    e,clock=exchange;a,token=e.create('practice','live')
    e.publish(q(T));e.submit(a['id'],buy());assert e.orders(a['id'])[0]['status']=='pending'
    # Same-time snapshot cannot execute a newly placed order.
    e.publish(q(T));assert e.orders(a['id'])[0]['status']=='pending'
    assert e.submit(a['id'],buy())['status']=='pending'
    with pytest.raises(ValueError):e.submit(a['id'],buy(budget='101'))
    clock[0]+=timedelta(seconds=1);e.publish(q(clock[0]));e.publish(q(clock[0]))
    orders=e.orders(a['id']);assert len(orders)==1 and orders[0]['status']=='filled'
    state=e.get(a['id']);f=orders[0]['fill'];debit=money(f['gross_tokens'])+money(f['fee_tokens'])
    assert money(state['cash_tokens'])+debit==500 and debit<=100
    assert len([x for x in e.history(a['id']) if x['kind']=='fill'])==1
    v=e.valuation(a['id']);assert Decimal(v['equity_tokens'])<500
    e.authorize(a['id'],token)
    with pytest.raises(PermissionError):e.authorize(a['id'],'wrong')


def test_reservations_no_overdraft_or_shorting(exchange):
    e,_=exchange;a,_=e.create('practice','live');e.submit(a['id'],buy(budget='400'))
    with pytest.raises(ValueError,match='available tokens'):e.submit(a['id'],buy('second','101'))
    with pytest.raises(ValueError,match='short'):e.submit(a['id'],OrderRequest(client_order_id='short',symbol='BTC-USD',source='coinbase_public',side='sell',quantity='1'))
    e.cancel(a['id'],'buy1');assert e.submit(a['id'],buy('replacement','500'))['status']=='pending'


def test_live_rejects_archive_stale_future_and_missing_marks(exchange):
    e,clock=exchange;a,_=e.create('practice','live')
    with pytest.raises(ValueError,match='archive'):e.submit(a['id'],buy(source='coinmetrics_reference'))
    with pytest.raises(ValueError,match='stale'):e.publish(q(T-timedelta(minutes=3)))
    with pytest.raises(ValueError,match='future'):e.publish(q(T+timedelta(seconds=3)))
    e.submit(a['id'],buy());clock[0]+=timedelta(seconds=1);e.publish(q(clock[0]))
    clock[0]+=timedelta(minutes=3);v=e.valuation(a['id'])
    assert v['equity_tokens'] is None and v['unpriced_positions']


def test_challenge_fixed_funding_deadline_dst_and_no_backdating(exchange):
    e,clock=exchange;r=ChallengeRunner(e,enabled=False);a=e.get('seven-day-agent')
    assert Decimal(a['initial_tokens'])==500 and Decimal(a['target_tokens'])==1000
    # Next week at the same Pacific wall time crosses DST: 169 elapsed hours.
    assert datetime.fromisoformat(a['deadline'])-REQUESTED_AT==timedelta(hours=169)
    assert a['deadline']=='2026-11-01T18:15:32+00:00'
    assert r.step()['status']=='awaiting_live_data'
    e.ensure_challenge(REQUESTED_AT);assert e.get(a['id'])['initial_tokens']==a['initial_tokens']
    clock[0]=datetime.fromisoformat(a['deadline']);v=r.step()
    assert v['status']=='expired' and v['goal_status']=='not_achieved'
    with pytest.raises(ValueError):e.submit(a['id'],buy())


def test_challenge_activation_retains_deadline_and_cash_policy(exchange):
    e,_=exchange;r=ChallengeRunner(e,enabled=True)
    e.publish(q(T));v=r.step()
    assert v['status']=='active' and v['cash_tokens']=='500.00000000'
    assert not e.orders('seven-day-agent')
    assert r.status()['decisions'][-1]['action']=='hold_cash'


def seed_prices(store):
    HistoryCatalog(store)
    dates=pd.date_range('2026-01-01',periods=12,tz='UTC')
    f=pd.DataFrame({'source':'coinmetrics_reference','symbol':'BTC-USD','timestamp':dates,'price':[100,101,102,103,104,105,106,107,108,109,110,111]})
    store.conn.register('fixture_prices',f);store.conn.execute('INSERT INTO price_observations SELECT * FROM fixture_prices');store.conn.unregister('fixture_prices')


def test_replay_asof_next_observation_and_duplicate_shared_quote(exchange):
    from paper.models import AccountRequest
    e,_=exchange;seed_prices(e.store);replay=HistoricalReplay(e)
    request=AccountRequest(name='replay',start='2026-01-01T00:00:00Z')
    a,_=replay.create(request);b,_=replay.create(request)
    e.submit(a['id'],buy(source='coinmetrics_reference'));replay.advance(a['id'])
    e.submit(b['id'],buy(source='coinmetrics_reference'));replay.advance(b['id'])
    for account in (a,b):
        assert e.orders(account['id'])[0]['status']=='filled'
        visible=replay.visible_prices(account['id']);assert len(visible)==2
        assert visible[-1]['close']==101
        assert e.orders(account['id'])[0]['fill']['market_time']=='2026-01-02T00:00:00+00:00'
    # Viewing the same replay state does not manufacture repeated equity samples.
    count=len(e.history(a['id']));e.valuation(a['id']);assert len(e.history(a['id']))==count


def test_roundtrip_realized_pnl_and_partial_sale(exchange):
    e,clock=exchange;a,_=e.create('practice','live');e.submit(a['id'],buy());clock[0]+=timedelta(seconds=1);e.publish(q(clock[0]))
    p=next(iter(e.get(a['id'])['positions'].values()));qty=units(Decimal(p['quantity'])/2)
    e.submit(a['id'],OrderRequest(client_order_id='sell',symbol='BTC-USD',source='coinbase_public',side='sell',quantity=qty))
    with pytest.raises(ValueError):e.submit(a['id'],OrderRequest(client_order_id='sell_more',symbol='BTC-USD',source='coinbase_public',side='sell',quantity=p['quantity']))
    clock[0]+=timedelta(seconds=1);e.publish(q(clock[0],price='110'))
    s=e.get(a['id']);assert Decimal(s['realized_pnl'])>0
    assert account_analytics(e,a['id'])['closed_fill_count']==1


def test_paper_api_security_and_replay(tmp_path):
    app=create_app(Settings(database_path=str(tmp_path/'test.duckdb'),demo=False,paper_live_poll=False,paper_auto_challenge=False))
    with TestClient(app) as client:
        seed_prices(app.state.store)
        assert client.get('/paper').status_code==200
        c=client.post('/api/paper/accounts',json={'name':'test','mode':'replay','start':'2026-01-01T00:00:00Z'}).json()
        account_id=c['account']['id'];headers={'Authorization':'Bearer '+c['access_key']}
        assert client.get('/api/paper/accounts/'+account_id).status_code==403
        assert client.get('/api/paper/accounts/'+account_id,headers=headers).status_code==200
        assert client.post('/api/paper/accounts/'+account_id+'/orders',headers=headers,json=buy(source='coinmetrics_reference').model_dump(mode='json')).status_code==201
        assert client.post('/api/paper/accounts/'+account_id+'/advance',headers=headers).status_code==200
        visible=client.get('/api/paper/accounts/'+account_id+'/history',headers=headers).json()['visible_prices'];assert len(visible)==2
        assert client.get('/api/paper/challenge').json()['account']['target_tokens']=='1000.00000000'


def test_deadline_uses_predeadline_quotes_and_ending_not_peak(exchange):
    e,clock=exchange;r=ChallengeRunner(e,enabled=True);e.publish(q(T));r.step()
    e.submit('seven-day-agent',buy(budget='500'));clock[0]+=timedelta(seconds=1);e.publish(q(clock[0]))
    clock[0]+=timedelta(seconds=1);e.publish(q(clock[0],price='300'))
    assert Decimal(e.valuation('seven-day-agent')['equity_tokens'])>1000
    deadline=datetime.fromisoformat(e.get('seven-day-agent')['deadline'])
    clock[0]=deadline-timedelta(seconds=1);e.publish(q(clock[0],price='100'))
    clock[0]=deadline+timedelta(seconds=1);e.publish(q(clock[0],price='1000'))
    final=e.valuation('seven-day-agent')
    assert final['target_observed_before_deadline'] is True
    assert final['goal_status']=='not_achieved' and Decimal(final['equity_tokens'])<500
    assert final['asof']==deadline.isoformat()


def test_small_order_rejection_does_not_block_other_accounts(exchange):
    e,clock=exchange;a,_=e.create('small','live');b,_=e.create('normal','live')
    e.submit(a['id'],buy(budget='0.00000001'));e.submit(b['id'],buy())
    clock[0]+=timedelta(seconds=1);assert e.publish(q(clock[0]))==1
    assert e.orders(a['id'])[0]['status']=='rejected'
    assert e.orders(b['id'])[0]['status']=='filled'
    assert e.get(a['id'])['cash_tokens']=='500.00000000'


def test_rehearsal_decisions_do_not_use_future_prices(exchange):
    from paper.rehearsal import episode
    import numpy as np
    e,_=exchange
    f=pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=50,tz='UTC'),'close':100*np.exp(np.arange(50)*.002)})
    original=episode(e,f,'BTC-USD',30,'momentum',10)
    changed=f.copy();changed.loc[35:,'close']*=1.5
    other=episode(e,changed,'BTC-USD',30,'momentum',10)
    assert original['orders'][0]==other['orders'][0]
    assert original['forecasts'][0]['prediction_up']==other['forecasts'][0]['prediction_up']


@pytest.mark.asyncio
async def test_coinbase_uses_real_bid_ask_and_provider_time(monkeypatch):
    import httpx
    from paper.live import fetch_coinbase
    monkeypatch.setattr('paper.live.destination_allowed',lambda host:True)
    def handler(request):return httpx.Response(200,json={'time':T.isoformat(),'bid':'99','ask':'101'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote=await fetch_coinbase('BTC-USD',client)
        assert quote.market_time==T and quote.bid==99 and quote.ask==101
        assert quote.source=='coinbase_public' and quote.mode=='live'
