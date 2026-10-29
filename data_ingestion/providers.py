"""Read-only Alpaca IEX feed and news adapters. No broker order endpoints."""
from datetime import datetime,timezone
import httpx

class Alpaca:
    def __init__(self,key,secret):self.headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
    async def latest(self,symbols):
        async with httpx.AsyncClient(timeout=12) as c:
            r=await c.get('https://data.alpaca.markets/v2/stocks/quotes/latest',params={'symbols':','.join(symbols),'feed':'iex'},headers=self.headers);r.raise_for_status()
            result={}
            for symbol,q in r.json()['quotes'].items():
                bid=float(q['bp']);ask=float(q['ap']);stamp=datetime.fromisoformat(q['t'].replace('Z','+00:00')).timestamp()
                if bid>0 and ask>=bid:result[symbol]=dict(bid=bid,ask=ask,time=stamp,mode='live',source='Alpaca IEX',observed_at=datetime.now(timezone.utc).timestamp())
            return result
    async def history(self,symbol):
        async with httpx.AsyncClient(timeout=20) as c:
            r=await c.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/bars',params={'timeframe':'1Min','limit':1000,'feed':'iex','adjustment':'all'},headers=self.headers);r.raise_for_status()
            return [dict(time=int(datetime.fromisoformat(b['t'].replace('Z','+00:00')).timestamp()),open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']) for b in r.json().get('bars',[])]
    async def news(self,symbols):
        async with httpx.AsyncClient(timeout=12) as c:
            r=await c.get('https://data.alpaca.markets/v1beta1/news',params={'symbols':','.join(symbols),'limit':30},headers=self.headers);r.raise_for_status()
            now=datetime.now(timezone.utc).timestamp()
            return [dict(id=str(n['id']),headline=n['headline'],symbols=n['symbols'],published_at=datetime.fromisoformat(n['created_at'].replace('Z','+00:00')).timestamp(),available_at=now,source=n['source'],url=n.get('url'),mode='live') for n in r.json().get('news',[])]
