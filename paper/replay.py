from datetime import datetime,timezone
from decimal import Decimal
import pandas as pd
from engine.research import load_series
from paper.models import Quote

class HistoricalReplay:
    def __init__(self,exchange):self.exchange=exchange;self.store=exchange.store
    def frame(self,source,symbol):
        f=load_series(self.store,source,symbol)
        if f.empty:raise ValueError('no daily history for this instrument/source')
        if source=='synthetic':raise ValueError('choose an actual historical source')
        return f
    def create(self,request):
        f=self.frame(request.source,request.symbol)
        start=pd.Timestamp(request.start) if request.start else f.timestamp.iloc[max(0,len(f)-8)]
        choices=f[f.timestamp>=start]
        if choices.empty:raise ValueError('start is beyond available history')
        cursor=choices.timestamp.iloc[0].to_pydatetime()
        a,token=self.exchange.create(request.name,'replay',request.initial_tokens,source=request.source,symbol=request.symbol,cursor=cursor)
        self.exchange.publish(self.quote(request.source,request.symbol,choices.iloc[0]))
        return a,token
    @staticmethod
    def quote(source,symbol,row):
        # A daily price label is a simulation clock, not precise publication time.
        price=Decimal(str(row.close));t=row.timestamp.to_pydatetime()
        return Quote(symbol=symbol,source=source,market_time=t,observed_at=t,bid=price*Decimal('.9995'),ask=price*Decimal('1.0005'),mode='replay',spread_basis='modeled 10 bps total spread around next observed daily price; not historical bid/ask')
    def advance(self,account_id):
        with self.store.lock:
            with self.exchange.transaction():
                a=self.exchange._load(account_id)
                if a['mode']!='replay':raise ValueError('only replay accounts can advance a historical clock')
                f=self.frame(a['source'],a['symbol']);future=f[f.timestamp>pd.Timestamp(a['cursor'])]
                if future.empty:raise ValueError('replay history exhausted')
                row=future.iloc[0];a['cursor']=row.timestamp.isoformat();self.exchange._save(a)
                self.exchange.publish(self.quote(a['source'],a['symbol'],row),within_transaction=True)
            return self.exchange.valuation(account_id)
    def visible_prices(self,account_id):
        a=self.exchange.get(account_id)
        if a['mode']!='replay':raise ValueError('only replay accounts have a historical clock')
        f=self.frame(a['source'],a['symbol'])
        return f[f.timestamp<=pd.Timestamp(a['cursor'])].tail(90)[['timestamp','close']].to_dict(orient='records')
