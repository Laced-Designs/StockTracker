"""Atomic simulated ledger: reservations, idempotent orders, collateral and expiry.

All cash is serialized as fixed-point decimal strings. No real-money API exists.
Options are hypothetical European cash-settled contracts, not listed-chain fills.
"""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from copy import deepcopy
import hashlib,hmac,json,secrets,uuid
from sqlalchemy import select
from api.storage import Account
from matching_engine.schemas import OrderRequest
from models.options import black_scholes
from matching_engine.calendar import market_status

D=Decimal
CENT=D('.000001')
def cash(value):return D(str(value)).quantize(CENT,rounding=ROUND_HALF_UP)
def iso():return datetime.now(timezone.utc).isoformat()
def position_key(o):return o['symbol'] if o['asset']=='equity' else f"{o['symbol']}:{o['right']}:{o['strike']}:{o['expiry']}"

class Broker:
    def __init__(self,store,market,settings):self.store=store;self.market=market;self.settings=settings
    def create(self,name,initial):
        id=uuid.uuid4().hex;key=secrets.token_urlsafe(32)
        state=dict(id=id,name=name,initial=str(cash(initial)),cash=str(cash(initial)),fees='0',positions={},orders=[],activity=[],curve=[],created_at=iso(),mode=self.settings.mode)
        with self.store.transaction() as s:s.add(Account(id=id,key_hash=hashlib.sha256(key.encode()).hexdigest(),state=state))
        return state,key
    def _load(self,s,id,key=None,internal=False):
        row=s.scalar(select(Account).where(Account.id==id).with_for_update())
        if row is None:raise PermissionError('Unknown account or invalid key')
        if not internal and not hmac.compare_digest(row.key_hash,hashlib.sha256((key or '').encode()).hexdigest()):raise PermissionError('Unknown account or invalid key')
        if row.state['mode']!=self.settings.mode:raise ValueError('Account belongs to another data mode')
        return row,deepcopy(row.state)
    def quote(self,o,now):
        q=self.market.quotes.get(o['symbol'])
        if not q or now-q['time']>30 or q['time']>now+2 or q['mode']!=self.settings.mode:raise ValueError('Fresh eligible quote unavailable')
        if self.settings.mode=='live' and not market_status(datetime.fromtimestamp(now,timezone.utc))['open']:raise ValueError('Market closed; order waits for regular session')
        if o['asset']=='equity':return cash(q['bid']),cash(q['ask'])
        expiry=datetime.fromisoformat(o['expiry']).timestamp();years=max(expiry-now,0)/(365*86400)
        premium=black_scholes((q['bid']+q['ask'])/2,float(o['strike']),years,self.market.volatility(o['symbol']),o['right'])['premium']
        return cash(max(premium*.97,.000001)),cash(max(premium*1.03,.000001))
    def reserved(self,a):
        return sum((D(o['reserve']) for o in a['orders'] if o['status']=='pending'),D(0))+sum((D(p.get('collateral','0')) for p in a['positions'].values()),D(0))
    def locked_units(self,a,key):
        pending=sum((D(o['quantity']) for o in a['orders'] if o['status']=='pending' and o['side'] in ('sell','sell_to_close','buy_to_close') and position_key(o)==key),D(0))
        if ':' not in key:
            pending+=sum((D(p['quantity'])*100 for p in a['positions'].values() if p.get('side')=='short' and p.get('right')=='call' and p['symbol']==key),D(0))
            pending+=sum((D(o['quantity'])*100 for o in a['orders'] if o['status']=='pending' and o['side']=='sell_to_open' and o['right']=='call' and o['symbol']==key),D(0))
        return pending
    def submit(self,id,key,body:OrderRequest):
        o=body.model_dump(mode='json');now=datetime.now(timezone.utc).timestamp()
        with self.store.transaction() as s:
            row,a=self._load(s,id,key)
            old=next((x for x in a['orders'] if x['client_id']==o['client_id']),None)
            if old:
                if old['request']!=o:raise ValueError('Client ID already used for a different order')
                return a
            if len(a['orders'])>=1000:raise ValueError('Account order limit reached')
            if o['symbol'] not in self.market.symbols:raise ValueError('Unsupported symbol')
            if o['asset']=='option' and (datetime.fromisoformat(o['expiry']).timestamp()<=now or datetime.fromisoformat(o['expiry']).timestamp()>now+366*86400):raise ValueError('Option expiry must be in the next year')
            bid,ask=self.quote(o,now);qty=D(o['quantity']);mult=100 if o['asset']=='option' else 1;k=position_key(o);position=a['positions'].get(k)
            buying=o['side'] in ('buy','buy_to_open','buy_to_close');reserve=D(0)
            if o['side'] in ('sell','sell_to_close','buy_to_close'):
                required='short' if o['side']=='buy_to_close' else 'long'
                if not position or position['side']!=required or D(position['quantity'])-self.locked_units(a,k)<qty:raise ValueError('Insufficient unreserved position')
            if o['side']=='buy_to_open' and position and position['side']=='short':raise ValueError('Close short contract first')
            if o['side']=='sell_to_open':
                if position and position['side']=='long':raise ValueError('Close long contract first')
                if o['right']=='call':
                    stock=a['positions'].get(o['symbol']);available=D(stock['quantity'])-self.locked_units(a,o['symbol']) if stock else D(0)
                    if available<qty*100:raise ValueError('Covered calls require 100 unreserved shares per contract')
                else:reserve=D(o['strike'])*qty*100
            if buying:
                ref=D(o['price']) if o['type']=='limit' else ask*D('1.02')
                reserve=ref*qty*mult*(1+D(self.settings.slippage_bps+self.settings.fee_bps)/10000)+(D('.65')*qty if mult==100 else 0)
            if D(a['cash'])-self.reserved(a)<reserve:raise ValueError('Insufficient available tokens including costs and collateral')
            if o['side']=='buy_to_close' and position:
                # Collateral stays locked until execution, preventing double use.
                pass
            from models.predictor import features
            frame=features(self.market.bars[o['symbol']],self.market.news(o['symbol'])) if len(self.market.bars[o['symbol']])>=30 else None
            technical=frame.iloc[-1].fillna(0).to_dict() if frame is not None else {}
            direction=(1 if o['side'] in ('buy','buy_to_open','buy_to_close') else -1)*(-1 if o['asset']=='option' and o['right']=='put' else 1)
            context=dict(directional_view=direction,technical=technical,quote_time=self.market.quotes[o['symbol']]['time'],quote_source=self.market.quotes[o['symbol']]['source'],mode=self.settings.mode,available_news=[dict(id=e['id'],sentiment=e['sentiment'],available_at=e['available_at']) for e in self.market.news(o['symbol']) if e['available_at']<=now][-5:])
            order=o|dict(context=context,request=deepcopy(o),status='pending',reserve=str(cash(reserve)),submitted_at=iso(),submitted_quote_time=self.market.quotes[o['symbol']]['time'])
            a['orders'].append(order);self.event(a,'order_submitted',{'symbol':o['symbol'],'side':o['side'],'quantity':o['quantity'],'client_id':o['client_id']});row.state=a
        return a
    def cancel(self,id,key,client_id):
        with self.store.transaction() as s:
            row,a=self._load(s,id,key);o=next((x for x in a['orders'] if x['client_id']==client_id),None)
            if not o or o['status']!='pending':raise ValueError('No pending order to cancel')
            o['status']='canceled';self.event(a,'order_canceled',{'client_id':client_id});row.state=a
        return a
    def event(self,a,kind,data):a['activity'].append(dict(id=uuid.uuid4().hex,time=iso(),kind=kind,data=data))
    def fill(self,a,o,now):
        q=self.market.quotes.get(o['symbol'])
        if not q or q['time']<=o['submitted_quote_time']:return
        bid,ask=self.quote(o,now);buy=o['side'] in ('buy','buy_to_open','buy_to_close');qty=D(o['quantity']);mult=100 if o['asset']=='option' else 1
        price=ask if buy else bid
        if o['type']=='limit' and ((buy and price>D(o['price'])) or (not buy and price<D(o['price']))):return
        if o['type']=='stop' and not o.get('triggered'):
            if (buy and price<D(o['price'])) or (not buy and price>D(o['price'])):return
            o['triggered']=True
        price=cash(price*(1+D(self.settings.slippage_bps)/10000*(1 if buy else -1)))
        if o['type']=='limit':price=min(price,D(o['price'])) if buy else max(price,D(o['price']))
        gross=cash(price*qty*mult);fee=cash(gross*D(self.settings.fee_bps)/10000+(D('.65')*qty if o['asset']=='option' else 0));k=position_key(o);p=a['positions'].get(k)
        available=D(a['cash'])-self.reserved(a)+D(o['reserve'])
        if buy and gross+fee>available:raise ValueError('Execution exceeds funded budget after price change')
        opening=o['side'] in ('buy','buy_to_open','sell_to_open')
        if not opening and (not p or D(p['quantity'])<qty):raise ValueError('Position no longer available')
        if buy:a['cash']=str(cash(D(a['cash'])-gross-fee))
        else:
            if gross<fee:raise ValueError('Premium proceeds do not cover fees')
            a['cash']=str(cash(D(a['cash'])+gross-fee))
        realized=None
        if opening:
            if not p:
                p={k2:o[k2] for k2 in ['symbol','asset','right','strike','expiry']};p.update(entry_context=o.get('context',{}),quantity='0',cost='0',side='short' if o['side']=='sell_to_open' else 'long',collateral='0');a['positions'][k]=p
            p['quantity']=str(D(p['quantity'])+qty);p['cost']=str(D(p['cost'])+gross+(fee if buy else -fee))
            if o['side']=='sell_to_open' and o['right']=='put':p['collateral']=str(D(p['collateral'])+D(o['strike'])*qty*100)
        else:
            o['entry_context']=p.get('entry_context',{});fraction=qty/D(p['quantity']);basis=D(p['cost'])*fraction
            realized=basis-gross-fee if p['side']=='short' else gross-fee-basis
            p['quantity']=str(D(p['quantity'])-qty);p['cost']=str(D(p['cost'])-basis);p['collateral']=str(D(p.get('collateral','0'))*(1-fraction))
            if D(p['quantity'])==0:del a['positions'][k]
        a['fees']=str(cash(D(a['fees'])+fee));o.update(status='filled',filled_at=iso(),fill_price=str(price),fee=str(fee),realized_pnl=str(cash(realized)) if realized is not None else None)
        self.event(a,'fill',{k:o.get(k) for k in ['symbol','side','quantity','fill_price','fee','realized_pnl']})
    def expire(self,a,now):
        for k,p in list(a['positions'].items()):
            if p['asset']!='option' or datetime.fromisoformat(p['expiry']).timestamp()>now:continue
            expiry=datetime.fromisoformat(p['expiry']).timestamp()
            for order in a['orders']:
                if order['status']=='pending' and position_key(order)==k:
                    order.update(status='expired',reason='Contract expired');self.event(a,'order_expired',{'client_id':order['client_id']})
            # Settlement must be captured at expiry, never invented after downtime.
            q=self.market.quotes.get(p['symbol'])
            if not q or abs(q['time']-expiry)>30:
                p['settlement_status']='Awaiting verifiable expiry-time price';continue
            spot=(q['bid']+q['ask'])/2;intrinsic=max((spot-float(p['strike']))*(1 if p['right']=='call' else -1),0);payment=cash(intrinsic*float(p['quantity'])*100)
            if p['side']=='short':
                # Covered calls cash-settle by selling the locked shares at the same mark.
                if p['right']=='call' and payment>0:
                    stock=a['positions'].get(p['symbol']);n=D(p['quantity'])*100
                    proceeds=cash(n*D(str(q['bid'])));a['cash']=str(D(a['cash'])+proceeds)
                    ratio=n/D(stock['quantity']);stock['quantity']=str(D(stock['quantity'])-n);stock['cost']=str(D(stock['cost'])*(1-ratio))
                    if D(stock['quantity'])==0:del a['positions'][p['symbol']]
                a['cash']=str(cash(D(a['cash'])-payment))
            else:a['cash']=str(cash(D(a['cash'])+payment))
            self.event(a,'option_expired',{'symbol':p['symbol'],'settlement':str(payment),'right':p['right'],'worthless':payment==0});del a['positions'][k]
        for o in a['orders']:
            if o['status']=='pending' and o['asset']=='option' and datetime.fromisoformat(o['expiry']).timestamp()<=now:o.update(status='expired',reason='Contract expired')
    def process(self):
        now=datetime.now(timezone.utc).timestamp()
        with self.store.transaction() as s:
            for row in s.scalars(select(Account).with_for_update()):
                a=deepcopy(row.state)
                if a['mode']!=self.settings.mode:continue
                self.expire(a,now)
                for o in a['orders']:
                    if o['status']!='pending':continue
                    try:self.fill(a,o,now)
                    except ValueError as exc:
                        if 'Market closed' in str(exc) or 'quote unavailable' in str(exc):continue
                        o.update(status='rejected',reason=str(exc));self.event(a,'order_rejected',{'client_id':o['client_id'],'reason':str(exc)})
                value=self.value(a,now)
                if value['equity'] is not None:a['curve']=(a['curve']+[{'time':iso(),'equity':value['equity']}])[-2000:]
                row.state=a
    def value(self,a,now=None):
        now=now or datetime.now(timezone.utc).timestamp();equity=D(a['cash']);positions=[];missing=[];option_delta_notional=0.;greeks={k:0. for k in ('delta','gamma','theta','vega')}
        for key,p in a['positions'].items():
            try:
                if p.get('settlement_status'):raise ValueError('Settlement missing')
                bid,ask=self.quote(p,now);qty=D(p['quantity']);mult=100 if p['asset']=='option' else 1;sign=1 if p['side']=='long' else -1
                price=bid if sign==1 else ask;value=cash(price*qty*mult*sign);exit_fee=cash(abs(value)*D(self.settings.fee_bps)/10000+(D('.65')*qty if mult==100 else 0));equity+=value-exit_fee-cash(abs(value)*D(self.settings.slippage_bps)/10000)
                item=p|{'key':key,'mark':str(price),'market_value':str(value),'pnl':str(value-D(p['cost'])*sign)}
                if mult==100:
                    q=self.market.quotes[p['symbol']];g=black_scholes((q['bid']+q['ask'])/2,float(p['strike']),max(0,(datetime.fromisoformat(p['expiry']).timestamp()-now)/(365*86400)),self.market.volatility(p['symbol']),p['right'])
                    option_delta_notional+=abs(g['delta']*float(qty)*100*(q['bid']+q['ask'])/2)
                    for k in greeks:greeks[k]+=g[k]*float(qty)*100*sign
                else:greeks['delta']+=float(qty)
                positions.append(item)
            except ValueError:missing.append(p['symbol']);positions.append(p|{'key':key,'mark':None,'market_value':None,'pnl':None})
        curve=[float(v['equity']) for v in a['curve']];peak=float(a['initial']);dd=0.
        for v in curve:peak=max(peak,v);dd=max(dd,(peak-v)/peak)
        return dict(equity=None if missing else str(cash(equity)),cash=a['cash'],reserved=str(cash(self.reserved(a))),available=str(cash(D(a['cash'])-self.reserved(a))),positions=positions,fees=a['fees'],greeks=greeks,option_delta_notional=option_delta_notional,option_leverage=None if missing or equity<=0 else option_delta_notional/float(equity),max_drawdown=dd,missing_marks=missing,sharpe=None,beta=None,risk_note='Beta and Sharpe need aligned benchmark returns over sufficient sessions; unavailable for this short/demo sample.',asof=iso())
    def snapshot(self,id,key):
        with self.store.transaction() as s:row,a=self._load(s,id,key)
        return dict(account=a,valuation=self.value(a),postmortems=self.postmortems(a))
    def postmortems(self,a):
        reports=[]
        for order in a['orders']:
            if order['status']!='filled' or order.get('realized_pnl') is None:continue
            context=order.get('entry_context',{});direction=context.get('directional_view',0)
            technical=context.get('technical',{});momentum=technical.get('momentum',0)
            news=context.get('available_news',[])
            sentiment=sum(e['sentiment'] for e in news)/len(news) if news else None
            reports.append(dict(time=order.get('filled_at'),symbol=order['symbol'],pnl=order['realized_pnl'],
                feedback=dict(momentum_alignment='Aligned' if direction*momentum>0 else 'Opposed' if direction*momentum<0 else 'Neutral / unavailable',
                    news_alignment='Unavailable' if sentiment is None else 'Aligned' if direction*sentiment>0 else 'Opposed' if direction*sentiment<0 else 'Neutral',
                    entry_rsi=technical.get('rsi'),available_news_count=len(news)),
                note='Alignment uses entry-time momentum and available sentiment, not later headlines. Costs are included in realized P/L; alignment does not establish causation or trade quality.',context=context))
        return reports[-20:]
