"""Long-only, fully funded simulated exchange. One token equals one USD.
All balances use Decimal strings; writes and idempotency are transactional.
"""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal,ROUND_DOWN,ROUND_HALF_EVEN
import hashlib,hmac,json,secrets,uuid
from contextlib import contextmanager,nullcontext
from paper.models import Quote,OrderRequest

D=Decimal
MONEY=D('.00000001');UNITS=D('.000000000001')
LIVE_SOURCES={'coinbase_public','alpaca_iex'}
def money(x):return D(str(x)).quantize(MONEY,rounding=ROUND_HALF_EVEN)
def units(x):return D(str(x)).quantize(UNITS,rounding=ROUND_DOWN)
def utcnow():return datetime.now(timezone.utc)
def stamp(s):return datetime.fromisoformat(s)
def key(symbol,source):return source+':'+symbol

class PaperExchange:
    def __init__(self,store,clock=utcnow):
        self.store=store;self.clock=clock
        with store.lock:
            store.conn.execute("""CREATE TABLE IF NOT EXISTS paper_accounts (id VARCHAR PRIMARY KEY,access_hash VARCHAR,state JSON);
            CREATE TABLE IF NOT EXISTS paper_orders (account_id VARCHAR,client_order_id VARCHAR,created_at TIMESTAMPTZ,status VARCHAR,payload JSON,result JSON,PRIMARY KEY(account_id,client_order_id));
            CREATE TABLE IF NOT EXISTS paper_quotes (id VARCHAR PRIMARY KEY,source VARCHAR,symbol VARCHAR,market_time TIMESTAMPTZ,observed_at TIMESTAMPTZ,mode VARCHAR,payload JSON);
            CREATE TABLE IF NOT EXISTS paper_events (id VARCHAR PRIMARY KEY,account_id VARCHAR,event_time TIMESTAMPTZ,kind VARCHAR,payload JSON);
            CREATE TABLE IF NOT EXISTS paper_trials (id VARCHAR PRIMARY KEY,created_at TIMESTAMPTZ,summary JSON);
            CREATE TABLE IF NOT EXISTS paper_decisions (id VARCHAR PRIMARY KEY,account_id VARCHAR,created_at TIMESTAMPTZ,payload JSON);
            """)
            store.conn.execute("CREATE SEQUENCE IF NOT EXISTS paper_event_seq; ALTER TABLE paper_events ADD COLUMN IF NOT EXISTS seq BIGINT")
    @contextmanager
    def transaction(self):
        with self.store.lock:
            self.store.conn.execute('BEGIN')
            try:yield;self.store.conn.execute('COMMIT')
            except BaseException:self.store.conn.execute('ROLLBACK');raise
    def _load(self,account_id):
        row=self.store.conn.execute('SELECT state FROM paper_accounts WHERE id=?',[account_id]).fetchone()
        if row is None:raise ValueError('unknown paper account')
        return json.loads(row[0])
    def _save(self,a):self.store.conn.execute('UPDATE paper_accounts SET state=? WHERE id=?',[json.dumps(a),a['id']])
    def _event(self,a,kind,payload,time=None):
        self.store.conn.execute("INSERT INTO paper_events (id,account_id,event_time,kind,payload,seq) VALUES (?,?,?,?,?,nextval('paper_event_seq'))",[uuid.uuid4().hex,a['id'],time or self.clock(),kind,json.dumps(payload)])
    def authorize(self,account_id,token):
        with self.store.lock:row=self.store.conn.execute('SELECT access_hash FROM paper_accounts WHERE id=?',[account_id]).fetchone()
        if row is None or not token or not hmac.compare_digest(row[0],hashlib.sha256(token.encode()).hexdigest()):raise PermissionError('invalid paper-account access key')
    def create(self,name,mode='replay',initial=500,*,source=None,symbol=None,cursor=None,challenge=False,requested_at=None,account_id=None):
        initial=money(initial)
        if initial<=0 or initial>100000:raise ValueError('invalid paper funding')
        if mode not in ('live','replay'):raise ValueError('unknown paper mode')
        if challenge and (initial!=500 or mode!='live'):raise ValueError('challenge is exactly 500 live-paper tokens')
        if mode=='replay' and (not source or not symbol or cursor is None):raise ValueError('replay instrument and cursor required')
        now=requested_at or self.clock();account_id=account_id or uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        deadline=((now.astimezone(ZoneInfo('America/Los_Angeles'))+timedelta(days=7)).astimezone(timezone.utc)) if challenge else None
        state=dict(id=account_id,name=name,mode=mode,initial_tokens=str(initial),cash_tokens=str(initial),
           positions={},realized_pnl='0.00000000',fees_tokens='0.00000000',turnover_tokens='0.00000000',
           token_usd='1.00',status='awaiting_live_data' if challenge else 'active',challenge=challenge,
           target_tokens='1000.00000000' if challenge else None,created_at=now.isoformat(),started_at=None,
           deadline=deadline.isoformat() if deadline else None,source=source,symbol=symbol,
           cursor=cursor.isoformat() if cursor else None,fee_bps='10',slippage_bps='5',max_quote_age_seconds=120,
           policy='long-only, fully funded; no deposits, borrowing, leverage or real orders',initial_benchmarks={},last_valuation=None,
           target_observed_before_deadline=False)
        with self.transaction():
            self.store.conn.execute('INSERT INTO paper_accounts VALUES (?,?,?)',[account_id,hashlib.sha256(token.encode()).hexdigest(),json.dumps(state)])
            self._event(state,'initial_funding',{'tokens':str(initial),'usd_per_token':'1.00'},cursor or now)
        return state,token
    def get(self,account_id):
        with self.store.lock:return self._load(account_id)
    def ensure_challenge(self,requested_at):
        with self.store.lock:
            row=self.store.conn.execute("SELECT id FROM paper_accounts WHERE id='seven-day-agent'").fetchone()
        if row:return self.get(row[0]),None
        return self.create('Agent seven-day challenge','live',500,challenge=True,requested_at=requested_at,account_id='seven-day-agent')
    def orders(self,account_id):
        with self.store.lock:
            rows=self.store.conn.execute('SELECT client_order_id,created_at,status,payload,result FROM paper_orders WHERE account_id=? ORDER BY created_at,client_order_id',[account_id]).fetchall()
        return [dict(client_order_id=i,created_at=t.isoformat(),status=s,order=json.loads(p),fill=json.loads(r) if r else None) for i,t,s,p,r in rows]
    def latest_quote(self,symbol,source,mode,asof=None):
        now=asof or self.clock()
        with self.store.lock:row=self.store.conn.execute('SELECT payload FROM paper_quotes WHERE symbol=? AND source=? AND mode=? AND market_time<=? AND observed_at<=? ORDER BY market_time DESC,observed_at DESC LIMIT 1',[symbol,source,mode,now,now]).fetchone()
        return Quote.model_validate_json(row[0]) if row else None
    def fresh(self,q,now):
        return q is not None and q.market_time<=now+timedelta(seconds=2) and q.observed_at<=now+timedelta(seconds=2) and (now-q.market_time).total_seconds()<=120 and (now-q.observed_at).total_seconds()<=120
    def submit(self,account_id,order:OrderRequest):
        payload=order.model_dump_json()
        with self.transaction():
            old=self.store.conn.execute('SELECT payload FROM paper_orders WHERE account_id=? AND client_order_id=?',[account_id,order.client_order_id]).fetchone()
            if old:
                if json.loads(old[0])!=json.loads(payload):raise ValueError('client_order_id already used for a different order')
                return next(x for x in self.orders(account_id) if x['client_order_id']==order.client_order_id)
            a=self._load(account_id);now=stamp(a['cursor']) if a['mode']=='replay' else self.clock()
            if a['status']!='active':raise ValueError('paper account is not active')
            if a['deadline'] and now>=stamp(a['deadline']):raise ValueError('challenge deadline passed')
            if a['mode']=='live' and order.source not in LIVE_SOURCES:raise ValueError('archive data cannot fill live orders')
            if a['mode']=='replay' and (a['source'],a['symbol'])!=(order.source,order.symbol):raise ValueError('replay account is pinned to its instrument and source')
            pending=self.orders(account_id)
            if order.side=='buy':
                reserved=sum((D(x['order']['token_budget']) for x in pending if x['status']=='pending' and x['order']['side']=='buy'),D(0))
                if order.token_budget>money(a['cash_tokens'])-reserved:raise ValueError('insufficient available tokens')
            else:
                k=key(order.symbol,order.source);position=a['positions'].get(k,{})
                reserved=sum((D(x['order']['quantity']) for x in pending if x['status']=='pending' and x['order']['side']=='sell' and key(x['order']['symbol'],x['order']['source'])==k),D(0))
                if order.quantity>D(position.get('quantity','0'))-reserved:raise ValueError('insufficient available position; short selling is disabled')
            self.store.conn.execute("INSERT INTO paper_orders VALUES (?,?,?,'pending',?,NULL)",[account_id,order.client_order_id,now,payload])
            self._event(a,'order_submitted',json.loads(payload),now)
        return next(x for x in self.orders(account_id) if x['client_order_id']==order.client_order_id)
    def cancel(self,account_id,client_order_id):
        with self.transaction():
            result=self.store.conn.execute("UPDATE paper_orders SET status='canceled' WHERE account_id=? AND client_order_id=? AND status='pending' RETURNING client_order_id",[account_id,client_order_id]).fetchone()
            if not result:raise ValueError('no pending order to cancel')
            self._event(self._load(account_id),'order_canceled',{'client_order_id':client_order_id})
    def publish(self,q:Quote,within_transaction=False):
        if q.mode=='live':
            if q.source not in LIVE_SOURCES or not self.fresh(q,self.clock()):raise ValueError('unverified, stale or future live quote')
        quote_id=hashlib.sha256(q.model_dump_json().encode()).hexdigest()
        with (nullcontext() if within_transaction else self.transaction()):
            inserted=self.store.conn.execute('INSERT OR IGNORE INTO paper_quotes VALUES (?,?,?,?,?,?,?) RETURNING id',[quote_id,q.source,q.symbol,q.market_time,q.observed_at,q.mode,q.model_dump_json()]).fetchone()
            rows=self.store.conn.execute("SELECT account_id,client_order_id,created_at,payload FROM paper_orders WHERE status='pending' AND created_at<? ORDER BY created_at,client_order_id",[q.market_time]).fetchall()
            count=0
            for account_id,client_id,created,payload in rows:
                order=OrderRequest.model_validate_json(payload);a=self._load(account_id)
                if (order.symbol,order.source,a['mode'])!=(q.symbol,q.source,q.mode):continue
                if a['mode']=='replay' and stamp(a['cursor'])!=q.market_time:continue
                if a['status']!='active' or (a['deadline'] and q.market_time>=stamp(a['deadline'])):continue
                # A live fill also has to be observed before expiry, never backdated after downtime.
                if a['deadline'] and q.observed_at>=stamp(a['deadline']):continue
                try:
                    self._fill(a,order,q,quote_id);count+=1
                except ValueError as exc:
                    reason={'reason':str(exc),'quote_id':quote_id}
                    self.store.conn.execute("UPDATE paper_orders SET status='rejected',result=? WHERE account_id=? AND client_order_id=?",[json.dumps(reason),account_id,client_id])
                    self._event(a,'order_rejected',reason,q.market_time)
            return count
    def _fill(self,a,o,q,quote_id):
        fee_rate=D(a['fee_bps'])/10000;slip=D(a['slippage_bps'])/10000
        price=(q.ask*(1+slip)) if o.side=='buy' else (q.bid*(1-slip))
        k=key(o.symbol,o.source);position=a['positions'].get(k,{'symbol':o.symbol,'source':o.source,'quantity':'0','cost_basis':'0'})
        qty=units(max(D(0),o.token_budget-2*MONEY)/(price*(1+fee_rate))) if o.side=='buy' else o.quantity
        gross=money(qty*price);fee=money(gross*fee_rate);realized=D(0)
        if qty<=0:raise ValueError('order is too small to fill')
        if o.side=='buy':
            debit=gross+fee
            if debit>money(a['cash_tokens']) or debit>o.token_budget:raise ValueError('insufficient tokens at fill')
            a['cash_tokens']=str(money(a['cash_tokens'])-debit)
            position['quantity']=str(units(D(position['quantity'])+qty));position['cost_basis']=str(money(position['cost_basis'])+debit)
        else:
            oldqty=D(position['quantity'])
            if qty>oldqty:raise ValueError('oversell at fill')
            basis=money(D(position['cost_basis'])*qty/oldqty)
            realized=gross-fee-basis
            a['cash_tokens']=str(money(a['cash_tokens'])+gross-fee)
            position['quantity']=str(units(oldqty-qty));position['cost_basis']=str(money(position['cost_basis'])-basis)
        a['positions'][k]=position
        a['realized_pnl']=str(money(a['realized_pnl'])+realized)
        a['fees_tokens']=str(money(a['fees_tokens'])+fee);a['turnover_tokens']=str(money(a['turnover_tokens'])+gross)
        fill=dict(quote_id=quote_id,symbol=o.symbol,source=o.source,side=o.side,quantity=str(qty),price=str(price),gross_tokens=str(gross),fee_tokens=str(fee),realized_pnl=str(realized),market_time=q.market_time.isoformat(),observed_at=q.observed_at.isoformat(),spread_basis=q.spread_basis)
        self._save(a)
        self.store.conn.execute("UPDATE paper_orders SET status='filled',result=? WHERE account_id=? AND client_order_id=?",[json.dumps(fill),a['id'],o.client_order_id])
        self._event(a,'fill',fill,q.market_time)
    def valuation(self,account_id):
        with self.transaction():
            a=self._load(account_id);now=stamp(a['cursor']) if a['mode']=='replay' else self.clock()
            if a['deadline'] and now>=stamp(a['deadline']):
                a['status']='expired'
                self.store.conn.execute("UPDATE paper_orders SET status='expired' WHERE account_id=? AND status='pending'",[account_id])
            valuation_time=min(now,stamp(a['deadline'])) if a['deadline'] else now
            value=money(a['cash_tokens']);missing=[];positions=[]
            for k,p in a['positions'].items():
                qty=D(p['quantity'])
                if qty<=0:continue
                q=self.latest_quote(p['symbol'],p['source'],a['mode'],valuation_time)
                valid=q is not None and (a['mode']=='replay' and q.market_time==valuation_time or a['mode']=='live' and self.fresh(q,valuation_time))
                if not valid:missing.append(k);positions.append(p|{'value_tokens':None});continue
                # Net liquidation includes modeled exit slippage and fees.
                mark=money(qty*q.bid*(1-D(a['slippage_bps'])/10000)*(1-D(a['fee_bps'])/10000))
                value+=mark;positions.append(p|{'value_tokens':str(mark),'quote_time':q.market_time.isoformat()})
            result=dict(account_id=account_id,asof=valuation_time.isoformat(),recorded_at=now.isoformat(),cash_tokens=a['cash_tokens'],equity_tokens=None if missing else str(value),
              pnl_tokens=None if missing else str(value-money(a['initial_tokens'])),return_pct=None if missing else float((value/money(a['initial_tokens'])-1)*100),
              realized_pnl=a['realized_pnl'],fees_tokens=a['fees_tokens'],positions=positions,unpriced_positions=missing,status=a['status'],mode=a['mode'],token_usd='1.00',
              target_tokens=a['target_tokens'],deadline=a['deadline'],valuation_basis='cash plus net liquidation at fresh bid, modeled exit costs included')
            if not missing:
                a['last_valuation']=result
                if a['challenge'] and valuation_time<=stamp(a['deadline']) and value>=1000:a['target_observed_before_deadline']=True
            result['target_observed_before_deadline']=a['target_observed_before_deadline']
            result['goal_status']='no_challenge' if not a['challenge'] else ('unverified_final_value' if a['status']=='expired' and missing else 'target_met_at_deadline' if a['status']=='expired' and value>=1000 else 'not_achieved' if a['status']=='expired' else 'target_currently_met' if not missing and value>=1000 else 'pending')
            previous=a.get('_last_recorded_valuation')
            should_record=previous is None or previous.get('equity_tokens')!=result['equity_tokens'] or previous.get('status')!=result['status'] or (a['mode']=='replay' and previous.get('asof')!=result['asof']) or (a['mode']=='live' and (now-stamp(previous['asof'])).total_seconds()>=60)
            if should_record:a['_last_recorded_valuation']=result
            self._save(a)
            if should_record:self._event(a,'valuation',result,now)
            return result
    def history(self,account_id):
        with self.store.lock:
            rows=self.store.conn.execute('SELECT event_time,kind,payload FROM paper_events WHERE account_id=? ORDER BY event_time,seq',[account_id]).fetchall()
        return [dict(timestamp=t.isoformat(),kind=k,data=json.loads(p)) for t,k,p in rows]
    def decision(self,account_id,payload):
        with self.store.lock:self.store.conn.execute('INSERT INTO paper_decisions VALUES (?,?,?,?)',[uuid.uuid4().hex,account_id,self.clock(),json.dumps(payload)])
    def decisions(self,account_id):
        with self.store.lock:rows=self.store.conn.execute('SELECT created_at,payload FROM paper_decisions WHERE account_id=? ORDER BY created_at',[account_id]).fetchall()
        return [dict(timestamp=t.isoformat(),**json.loads(p)) for t,p in rows]
