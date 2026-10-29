import time
from copy import deepcopy
from decimal import Decimal
from datetime import datetime,timezone,timedelta
import pytest
from api.config import Settings
from api.storage import Store,Account
from data_ingestion.market import Market
from matching_engine.broker import Broker
from matching_engine.schemas import OrderRequest

@pytest.fixture
def setup():
    cfg=Settings(database_url='sqlite://',tick_seconds=3600);store=Store(cfg.database_url);market=Market(cfg,store);broker=Broker(store,market,cfg)
    a,k=broker.create('Test',10000)
    yield broker,market,a['id'],k
    store.close()

def order(**kw):return OrderRequest(**({'client_id':'one','symbol':'AAPL','quantity':1}|kw))
def advance(b,m,price=100):
    now=time.time();m.quotes['AAPL']=dict(bid=price,ask=price,time=now,observed_at=now,mode='demo',source='test');b.process()

def test_next_quote_fill_reservation_and_idempotency(setup):
    b,m,id,key=setup
    a=b.submit(id,key,order());assert a['orders'][0]['status']=='pending'
    b.process();assert b.snapshot(id,key)['account']['orders'][0]['status']=='pending'
    same=b.submit(id,key,order());assert len(same['orders'])==1
    with pytest.raises(ValueError):b.submit(id,key,order(quantity=2))
    advance(b,m)
    p=b.snapshot(id,key);assert p['account']['orders'][0]['status']=='filled'
    assert Decimal(p['valuation']['cash'])<9900 and p['valuation']['positions'][0]['quantity']=='1'
    assert p['account']['orders'][0]['context']['mode']=='demo'

def test_cash_reservations_cancel_and_auth(setup):
    b,m,id,key=setup
    with pytest.raises(PermissionError):b.snapshot(id,'bad')
    with pytest.raises(ValueError,match='Insufficient'):b.submit(id,key,order(quantity=100000))
    b.submit(id,key,order(type='limit',price=50,quantity=100))
    assert Decimal(b.snapshot(id,key)['valuation']['available'])<5000
    advance(b,m,100);assert b.snapshot(id,key)['account']['orders'][0]['status']=='pending'
    b.cancel(id,key,'one');assert b.snapshot(id,key)['valuation']['available']=='10000.000000'

def test_limit_stop_and_price_gap_rejection(setup):
    b,m,id,key=setup
    b.submit(id,key,order(type='limit',price=50));advance(b,m,40)
    assert Decimal(b.snapshot(id,key)['account']['orders'][0]['fill_price'])<=50
    b.submit(id,key,order(client_id='stop',side='sell',type='stop',price=35));advance(b,m,36)
    assert b.snapshot(id,key)['account']['orders'][-1]['status']=='pending'
    advance(b,m,30);assert Decimal(b.snapshot(id,key)['account']['orders'][-1]['fill_price'])<35
    b.submit(id,key,order(client_id='gap',quantity=250));advance(b,m,1000)
    p=b.snapshot(id,key);assert p['account']['orders'][-1]['status']=='rejected'
    assert Decimal(p['valuation']['cash'])>=0

def opt(**kw):return order(**({'asset':'option','right':'call','strike':100,'expiry':datetime.now(timezone.utc)+timedelta(days=14),'side':'buy_to_open'}|kw))

def test_options_whole_contract_and_fully_funded(setup):
    b,m,id,key=setup;advance(b,m,100)
    with pytest.raises(ValueError):opt(quantity=Decimal('1.5'))
    b.submit(id,key,opt());advance(b,m,101)
    p=b.snapshot(id,key);assert len(p['valuation']['positions'])==1
    assert Decimal(p['valuation']['positions'][0]['quantity'])==1
    assert p['valuation']['greeks']['delta']>0

def test_short_call_requires_shares_and_put_collateral(setup):
    b,m,id,key=setup;advance(b,m,100)
    with pytest.raises(ValueError,match='Covered'):b.submit(id,key,opt(side='sell_to_open'))
    with pytest.raises(ValueError,match='Insufficient'):b.submit(id,key,opt(side='sell_to_open',right='put',strike=200))
    a=b.submit(id,key,opt(side='sell_to_open',right='put',strike=90))
    assert Decimal(a['orders'][0]['reserve'])==9000
    advance(b,m,100);p=b.snapshot(id,key)
    assert Decimal(p['valuation']['reserved'])==9000
    assert Decimal(p['valuation']['available'])<1100

def test_stale_quote_and_mode_guard(setup):
    b,m,id,key=setup;m.quotes['AAPL']['time']=time.time()-31
    with pytest.raises(ValueError,match='quote'):b.submit(id,key,order())
    m.quotes['AAPL']['time']=time.time();m.quotes['AAPL']['mode']='live'
    with pytest.raises(ValueError,match='quote'):b.submit(id,key,order())

def test_expiry_otm_and_missing_expiry_mark(setup):
    b,m,id,key=setup;advance(b,m,100);exp=datetime.now(timezone.utc)+timedelta(seconds=5)
    o=opt(expiry=exp,strike=101);b.submit(id,key,o);advance(b,m,100)
    with b.store.transaction() as s:
        row=s.get(Account,id);a=deepcopy(row.state);p=next(iter(a['positions'].values()));p['expiry']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();row.state=a
    advance(b,m,100);snap=b.snapshot(id,key);assert not snap['valuation']['positions']
    assert any(e['kind']=='option_expired' and e['data']['worthless'] for e in snap['account']['activity'])
    # Offline gaps must not be settled using an invented expiry-time price.
    a={'positions':{'x':{'asset':'option','symbol':'AAPL','right':'call','strike':'100','expiry':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),'quantity':'1','side':'long','cost':'5'}},'orders':[],'activity':[],'cash':'500'}
    b.expire(a,time.time());assert 'x' in a['positions'] and 'settlement_status' in a['positions']['x']

def test_covered_call_locks_shares_and_cancels_release(setup):
    b,m,id,key=setup;advance(b,m,50)
    b.submit(id,key,order(quantity=100));advance(b,m,50)
    expiry=datetime.now(timezone.utc)+timedelta(days=14)
    b.submit(id,key,opt(client_id='covered',side='sell_to_open',strike=50,expiry=expiry))
    with pytest.raises(ValueError,match='Insufficient unreserved'):b.submit(id,key,order(client_id='sell-shares',side='sell',quantity=1))
    b.cancel(id,key,'covered')
    b.submit(id,key,order(client_id='sell-shares',side='sell',quantity=1));advance(b,m,50)
    assert Decimal(b.snapshot(id,key)['valuation']['positions'][0]['quantity'])==99

def test_simultaneous_reservations_cannot_double_spend(setup):
    from concurrent.futures import ThreadPoolExecutor
    b,m,id,key=setup;advance(b,m,100)
    def place(i):
        try:b.submit(id,key,order(client_id=str(i),quantity=60));return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(place,[1,2]))
    assert sum(result)==1
    assert Decimal(b.snapshot(id,key)['valuation']['available'])>=0

def test_account_survives_store_restart(tmp_path):
    cfg=Settings(database_url='sqlite:///'+str(tmp_path/'persist.db'))
    store=Store(cfg.database_url);market=Market(cfg,store);b=Broker(store,market,cfg);a,k=b.create('Persistent',500)
    b.submit(a['id'],k,order(type='limit',price=1));store.close()
    store=Store(cfg.database_url);b=Broker(store,Market(cfg,store),cfg)
    p=b.snapshot(a['id'],k);assert p['account']['orders'][0]['status']=='pending'
    assert Decimal(p['valuation']['available'])<500
    store.close()

def test_option_close_realized_costs_and_no_double_close(setup):
    b,m,id,key=setup;advance(b,m,100);expiry=datetime.now(timezone.utc)+timedelta(days=14)
    b.submit(id,key,opt(expiry=expiry));advance(b,m,101)
    b.submit(id,key,opt(client_id='close',expiry=expiry,side='sell_to_close'))
    with pytest.raises(ValueError,match='Insufficient unreserved'):b.submit(id,key,opt(client_id='close2',expiry=expiry,side='sell_to_close'))
    advance(b,m,102);snap=b.snapshot(id,key)
    assert not snap['valuation']['positions']
    assert Decimal(snap['valuation']['fees'])>1
    assert len(snap['postmortems'])==1 and snap['postmortems'][0]['pnl'] is not None

def test_put_short_close_releases_collateral(setup):
    b,m,id,key=setup;advance(b,m,100);expiry=datetime.now(timezone.utc)+timedelta(days=14)
    b.submit(id,key,opt(right='put',strike=90,expiry=expiry,side='sell_to_open'));advance(b,m,100)
    assert Decimal(b.snapshot(id,key)['valuation']['reserved'])==9000
    b.submit(id,key,opt(client_id='close',right='put',strike=90,expiry=expiry,side='buy_to_close'));advance(b,m,100)
    assert b.snapshot(id,key)['valuation']['reserved']=='0.000000'

def test_pending_orders_pause_on_stale_quotes(setup):
    b,m,id,key=setup;b.submit(id,key,order());m.quotes['AAPL']['time']=time.time()-120;b.process()
    assert b.snapshot(id,key)['account']['orders'][0]['status']=='pending'
    advance(b,m);assert b.snapshot(id,key)['account']['orders'][0]['status']=='filled'
