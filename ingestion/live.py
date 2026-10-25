import asyncio
import json
from datetime import datetime, timezone, timedelta
import websockets
from core.models import MarketTick, OHLCV

class MinuteAggregator:
    """Event-time finalized candles. Late trades are counted and excluded."""
    def __init__(self):
        self.state={}; self.late_ticks=0
    def add(self,tick):
        minute=tick.timestamp.replace(second=0,microsecond=0)
        key=(tick.source,tick.symbol)
        current=self.state.get(key)
        if current and minute<current["timestamp"]:
            self.late_ticks+=1; return None
        finished=None
        if current and minute>current["timestamp"]:
            finished=OHLCV(**current)
            current=None
        if current is None:
            current=dict(symbol=tick.symbol,timestamp=minute,interval="1m",source=tick.source,open=tick.price,high=tick.price,low=tick.price,close=tick.price,volume=0.)
            self.state[key]=current
        current["high"]=max(current["high"],tick.price)
        current["low"]=min(current["low"],tick.price)
        current["close"]=tick.price
        current["volume"]+=tick.size
        return finished

class AlpacaStream:
    def __init__(self,key,secret,symbols):
        if not key or not secret: raise ValueError("Alpaca credentials required")
        self.key=key;self.secret=secret;self.symbols=symbols
    async def run(self,on_tick):
        delay=1
        while True:
            try:
                async with websockets.connect("wss://stream.data.alpaca.markets/v2/iex",ping_interval=20,max_queue=1024) as ws:
                    await ws.send(json.dumps({"action":"auth","key":self.key,"secret":self.secret}))
                    authenticated=False
                    async for message in ws:
                        for event in json.loads(message):
                            if event.get("T")=="error":
                                raise ValueError(f"Alpaca stream error {event.get('code')}")
                            if event.get("msg")=="authenticated":
                                authenticated=True; delay=1
                                await ws.send(json.dumps({"action":"subscribe","trades":self.symbols}))
                            if authenticated and event.get("T")=="t":
                                await on_tick(MarketTick(symbol=event["S"],timestamp=event["t"],price=event["p"],size=event["s"],source="alpaca_iex",trade_id=str(event["i"])))
            except (OSError,websockets.ConnectionClosed):
                await asyncio.sleep(delay);delay=min(delay*2,60)
