"""Seven-calendar-day study ledger. It records observations, never fabricates time or fills."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import json,uuid,hashlib,asyncio
from decimal import Decimal
from paper.models import Quote,OrderRequest
from paper.ledger import PaperExchange
from ingestion.backfill import destination_allowed

class WeekStudy:
    def __init__(self,store,clock=None):
        self.store=store;self.clock=clock or (lambda:datetime.now(timezone.utc));self.exchange=PaperExchange(store,clock=self.clock)
        self.plan=json.loads(Path(__file__).with_name('study_plan.json').read_text())
        with store.lock:store.conn.execute('CREATE TABLE IF NOT EXISTS paper_study_checks (id VARCHAR PRIMARY KEY,study_id VARCHAR,day INTEGER,observed_at TIMESTAMPTZ,payload JSON); CREATE TABLE IF NOT EXISTS paper_study_arms (study_id VARCHAR,source VARCHAR,symbol VARCHAR,policy VARCHAR,account_id VARCHAR,PRIMARY KEY(study_id,source,symbol,policy))')
    def status(self):
        now=self.clock();start=datetime.fromisoformat(self.plan['created_at']);end=datetime.fromisoformat(self.plan['ends_at'])
        with self.store.lock:rows=self.store.conn.execute('SELECT payload FROM paper_study_checks WHERE study_id=? ORDER BY observed_at,id',[self.plan['id']]).fetchall()
        latest={}
        for row in rows:
            check=json.loads(row[0]);latest[check['day']]=check
        elapsed=max(0,min(7,(now.astimezone(ZoneInfo(self.plan['timezone'])).date()-start.astimezone(ZoneInfo(self.plan['timezone'])).date()).days))
        eligible=range(0,8) if now>=end else range(min(elapsed,6)+1)
        model_file=Path(__file__).resolve().parent.parent/'reports/week-study/options-model-summary.json'
        model=json.loads(model_file.read_text()) if model_file.exists() else {'status':'not_run'}
        return {'plan':self.plan,'asof':now.isoformat(),'phase':'complete_window' if now>=end else 'collecting' if now>=start else 'planned',
            'checkpoint_count':len(rows),'days_recorded':sorted(latest),'latest_daily_checks':[latest[x] for x in sorted(latest)],
            'missing_due_days':[i for i in eligible if i not in latest],
            'options_model':model,'quoted_options_execution':'not implemented; no actual option-chain connector or quoted fills',
            'final_is_due':now>=end,'original_challenge_unchanged':True,'spot_arms':self.arm_status()}
    def checkpoint(self):
        now=self.clock();start=datetime.fromisoformat(self.plan['created_at']);end=datetime.fromisoformat(self.plan['ends_at'])
        if now<start:raise ValueError('study has not started')
        day=max(0,min(7,(now.astimezone(ZoneInfo(self.plan['timezone'])).date()-start.astimezone(ZoneInfo(self.plan['timezone'])).date()).days))
        if now<end:day=min(day,6)
        cutoff=min(now,end)
        fresh=[]
        for source,symbol in [('coinbase_public','BTC-USD'),('coinbase_public','ETH-USD'),('alpaca_iex','SPY')]:
            q=self.exchange.latest_quote(symbol,source,'live',cutoff)
            if self.exchange.fresh(q,cutoff) and q.market_time>=start and q.observed_at>=start:fresh.append({'source':source,'symbol':symbol,'provider_time':q.market_time.isoformat(),'observed_at':q.observed_at.isoformat()})
        submitted=self.manage_spot()
        observation={'study_id':self.plan['id'],'day':day,'observed_at':now.isoformat(),'focus':self.plan['checkpoints'][day]['focus'],
             'spot_live_status':'quotes_observed_execution_must_be_verified_separately' if fresh else 'blocked_no_fresh_quotes',
             'fresh_quotes':fresh,'spot_orders_submitted_this_checkpoint':len(submitted),'quote_cutoff':cutoff.isoformat(),'spot_arms':self.arm_status(),'coinbase_destination_allowed':destination_allowed('api.exchange.coinbase.com'),
             'quoted_options_status':'blocked_no_option_chain_connector','quoted_option_fills':0,
             'note':'This checkpoint also invokes the eligible spot manager; submitted orders and fills are recorded separately in the ledger. It submits no quoted-option orders. Archived or theoretical results do not count as forward trades.'}
        with self.store.lock:self.store.conn.execute('INSERT INTO paper_study_checks VALUES (?,?,?,?,?)',[uuid.uuid4().hex,self.plan['id'],day,now,json.dumps(observation)])
        return observation
    def arm_status(self):
        with self.store.lock:rows=self.store.conn.execute('SELECT source,symbol,policy,account_id FROM paper_study_arms WHERE study_id=? ORDER BY source,symbol,policy',[self.plan['id']]).fetchall()
        return [{'source':src,'symbol':sym,'policy':policy,'valuation':self.exchange.valuation(account_id),'order_count':len(self.exchange.orders(account_id)),'filled_orders':sum(o['status']=='filled' for o in self.exchange.orders(account_id))} for src,sym,policy,account_id in rows]
    def manage_spot(self):
        now=self.clock();start=datetime.fromisoformat(self.plan['created_at']);end=datetime.fromisoformat(self.plan['ends_at'])
        if now<start or now>=end:return []
        submitted=[];e=self.exchange
        for source,symbol in [('coinbase_public','BTC-USD'),('coinbase_public','ETH-USD'),('alpaca_iex','SPY')]:
            q=e.latest_quote(symbol,source,'live',now)
            if not e.fresh(q,now) or q.market_time<start or q.observed_at<start:continue
            for policy in ('cash','buy_hold_25','buy_hold_100','momentum_25'):
                account_id=self.plan['id'].replace('-','_')+'_'+symbol.replace('-','_')+'_'+policy
                with self.store.lock:exists=self.store.conn.execute('SELECT 1 FROM paper_accounts WHERE id=?',[account_id]).fetchone()
                close_at=datetime.fromisoformat(self.plan['precommitted_exits']['SPY']) if symbol=='SPY' else end-timedelta(seconds=self.plan['precommitted_exits']['crypto_lead_seconds'])
                if not exists and now>=close_at:continue
                if not exists:
                    e.create('Week study '+symbol+' '+policy,'live',500,account_id=account_id)
                    with e.transaction():
                        a=e._load(account_id);a['deadline']=self.plan['ends_at'];e._save(a)
                    with self.store.lock:self.store.conn.execute('INSERT OR IGNORE INTO paper_study_arms VALUES (?,?,?,?,?)',[self.plan['id'],source,symbol,policy,account_id])
                a=e.get(account_id);orders=e.orders(account_id)
                if now>=close_at:
                    for pending in orders:
                        if pending['status']=='pending' and pending['order']['side']=='buy':e.cancel(account_id,pending['client_order_id'])
                    orders=e.orders(account_id)
                    position=next((p for p in a['positions'].values() if Decimal(p['quantity'])>0),None)
                    if position and not any(o['status']=='pending' for o in orders) and not any(o['client_order_id']=='window_exit' for o in orders):
                        submitted.append(e.submit(account_id,OrderRequest(client_order_id='window_exit',symbol=symbol,source=source,side='sell',quantity=position['quantity'])))
                    continue
                if policy=='cash' or any(o['status']=='pending' for o in orders):continue
                if policy.startswith('buy_hold'):
                    if orders:continue
                    order=OrderRequest(client_order_id='entry',symbol=symbol,source=source,side='buy',token_budget='125' if policy=='buy_hold_25' else '500')
                else:
                    with self.store.lock:raw=self.store.conn.execute("SELECT payload FROM paper_quotes WHERE source=? AND symbol=? AND mode='live' AND market_time>=? AND market_time<=? AND observed_at<=? ORDER BY market_time DESC,observed_at DESC LIMIT 200",[source,symbol,start,now,now]).fetchall()
                    bytime={}
                    for row in raw:
                        candidate=Quote.model_validate_json(row[0])
                        bytime.setdefault(candidate.market_time,(candidate.bid+candidate.ask)/2)
                    values=[bytime[t] for t in sorted(bytime)][-20:]
                    if len(values)<20:continue
                    signal=sum(values[-5:])/5>sum(values)/20 and values[-1]>values[-6]
                    position=next((p for p in a['positions'].values() if Decimal(p['quantity'])>0),None)
                    side=None
                    if position:
                        cost=Decimal(position['cost_basis'])/Decimal(position['quantity']);move=q.bid/cost-1
                        if not signal or move<=Decimal('-.05') or move>=Decimal('.05'):side='sell'
                    elif signal and Decimal(a['cash_tokens'])>=125:side='buy'
                    if side is None:continue
                    client_id='m_'+hashlib.sha256((q.market_time.isoformat()+side).encode()).hexdigest()[:24]
                    if any(o['client_order_id']==client_id for o in orders):continue
                    order=OrderRequest(client_order_id=client_id,symbol=symbol,source=source,side=side,token_budget='125' if side=='buy' else None,quantity=position['quantity'] if side=='sell' else None)
                submitted.append(e.submit(account_id,order))
        return submitted
    def export(self,path='reports/week-study/status.json'):
        out=Path(path);out.parent.mkdir(parents=True,exist_ok=True);snapshot=self.status()
        temporary=out.with_name(out.name+'.tmp');temporary.write_text(json.dumps(snapshot,indent=2));temporary.replace(out)
        return snapshot


async def study_loop(study,interval=60):
    while True:
        study.manage_spot()
        status=study.status()
        day=min(7,(study.clock().astimezone(ZoneInfo(study.plan['timezone'])).date()-datetime.fromisoformat(study.plan['created_at']).astimezone(ZoneInfo(study.plan['timezone'])).date()).days)
        if day not in status['days_recorded'] and (day<7 or status['final_is_due']):study.checkpoint()
        study.export()
        if status['final_is_due']:break
        await asyncio.sleep(interval)
