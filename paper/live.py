"""Public quote polling. The application has no real-money broker order code."""
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
from urllib.parse import quote
import httpx
from ingestion.backfill import destination_allowed
from paper.models import Quote

async def fetch_coinbase(symbol,client=None):
    if symbol not in ('BTC-USD','ETH-USD'):raise ValueError('paper live universe is BTC-USD/ETH-USD')
    host='api.exchange.coinbase.com'
    if destination_allowed(host) is False:raise ValueError('network policy blocks api.exchange.coinbase.com')
    async def get(c):
        response=await c.get(f'https://{host}/products/{quote(symbol,safe="")}/ticker',headers={'User-Agent':'StockTracker-Paper/1.0'})
        response.raise_for_status();data=response.json();now=datetime.now(timezone.utc)
        return Quote(symbol=symbol,source='coinbase_public',market_time=data['time'],observed_at=now,bid=Decimal(data['bid']),ask=Decimal(data['ask']),mode='live')
    if client is not None:return await get(client)
    async with httpx.AsyncClient(timeout=20) as c:return await get(c)

async def quote_loop(exchange,state,interval=60):
    while True:
        for symbol in ('BTC-USD','ETH-USD'):
            try:
                q=await fetch_coinbase(symbol);exchange.publish(q)
                state['last_success']=q.observed_at.isoformat();state['error']=None
            except (httpx.HTTPError,ValueError,KeyError) as exc:
                state['error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        await asyncio.sleep(interval)
