"""Single market publisher; bounded WebSocket fanout and optional Redis cache."""
import asyncio,json,logging,math,time
from datetime import datetime,timezone
import numpy as np
from api.storage import Store
from data_ingestion.mock import generate,events,PRICES
from data_ingestion.providers import Alpaca
from data_ingestion.sentiment import Sentiment

log=logging.getLogger(__name__)

class Market:
    def __init__(self,settings,store):
        self.settings=settings;self.store=store;self.symbols=settings.symbols.split(',');self.quotes={};self.bars={s:[] for s in self.symbols};self.events=[];self.listeners=set();self.redis=None;self.cache_status='Disabled';self.error=None;self.last_success=None;self.running=False;self.seq=0
        self.rng=np.random.default_rng(73);self.provider=Alpaca(settings.alpaca_key,settings.alpaca_secret);self.sentiment=Sentiment()
        if settings.mode=='demo':
            for s in self.symbols:
                if s not in PRICES:raise ValueError('Demo symbol not available')
                self.bars[s]=generate(s);self.events+=events(self.bars[s],s)
                price=self.bars[s][-1]['close'];now=time.time();self.quotes[s]=dict(bid=price*.9999,ask=price*1.0001,time=now,observed_at=now,mode='demo',source='Synthetic feed')
        else:
            for e in reversed(store.records('news',300)):self.events.append(e)
        self._last_bar_save={};self._last_news=0
    def volatility(self,symbol):
        prices=[b['close'] for b in self.bars[symbol][-120:]]
        if len(prices)<30:return .3
        return float(np.clip(np.std(np.diff(np.log(prices)))*math.sqrt(252*390),.05,2))
    async def initialize(self):
        if self.settings.redis_url:
            try:
                from redis.asyncio import Redis
                self.redis=Redis.from_url(self.settings.redis_url,socket_connect_timeout=2,socket_timeout=2);await self.redis.ping();self.cache_status='Connected'
            except Exception:self.cache_status='Unavailable; local fallback'
        if self.settings.mode=='live':
            if not self.settings.alpaca_key or not self.settings.alpaca_secret:self.error='Alpaca read-only data credentials are not configured';return
            for s in self.symbols:
                try:self.bars[s]=await self.provider.history(s)
                except Exception as exc:self.error=f'History unavailable ({type(exc).__name__})'
    async def step(self):
        now=time.time()
        if self.settings.mode=='demo':
            for s in self.symbols:
                q=self.quotes[s];price=(q['bid']+q['ask'])/2*math.exp(self.rng.normal(0,.0002))
                self.quotes[s]=dict(bid=price*.9999,ask=price*1.0001,time=now,observed_at=now,mode='demo',source='Synthetic feed')
        else:
            if not self.settings.alpaca_key or not self.settings.alpaca_secret:raise ValueError('Live data requires Alpaca credentials')
            self.quotes.update(await self.provider.latest(self.symbols))
            if now-self._last_news>=60:
                for e in await self.provider.news(self.symbols):
                    if not any(x['id']==e['id'] for x in self.events):
                        e.update(self.sentiment.analyze(e['headline']));self.events.append(e);self.store.record('news','news-'+e['id'],e)
                self.events=self.events[-300:];self._last_news=now
        for s,q in self.quotes.items():
            if now-q['time']>30:continue
            bucket=int(q['time']//60)*60;price=(q['bid']+q['ask'])/2;bars=self.bars[s]
            if bars and bars[-1]['time']==bucket:
                b=bars[-1];b.update(high=max(b['high'],price),low=min(b['low'],price),close=price)
            elif not bars or bucket>bars[-1]['time']:
                if bars:
                    self.store.record('bar',f"{self.settings.mode}-{s}-{bars[-1]['time']}",dict(symbol=s,mode=self.settings.mode,**bars[-1]))
                bars.append(dict(time=bucket,open=price,high=price,low=price,close=price,volume=0));self.bars[s]=bars[-1500:]
        self.last_success=datetime.now(timezone.utc).isoformat();self.error=None;self.seq+=1
        payload=dict(type='quotes',seq=self.seq,quotes=self.quotes,mode=self.settings.mode,asof=self.last_success)
        if self.redis:
            try:
                await self.redis.set('stocktracker:quotes',json.dumps(payload),ex=30);await self.redis.publish('stocktracker:ticks',json.dumps(payload));self.cache_status='Connected'
            except Exception:self.cache_status='Unavailable; local fallback'
        for queue in tuple(self.listeners):
            if queue.full():queue.get_nowait()
            queue.put_nowait(payload)
    async def run(self,broker):
        self.running=True
        try:
            while True:
                try:await self.step();broker.process()
                except Exception as exc:
                    self.error=f'Feed/processing unavailable ({type(exc).__name__})';log.exception('market_cycle_failed')
                await asyncio.sleep(self.settings.tick_seconds)
        finally:self.running=False
    def news(self,symbol):return [e for e in self.events if e.get('symbol')==symbol or symbol in e.get('symbols',[])][-30:]
    def depth(self,symbol):
        if self.settings.mode!='demo':return {'bids':[],'asks':[],'label':'Level 2 feed not configured'}
        q=self.quotes[symbol];return dict(bids=[{'price':round(q['bid']-i*.01,2),'size':int(180+((i*139+self.seq*17)%800))} for i in range(8)],asks=[{'price':round(q['ask']+i*.01,2),'size':int(130+((i*173+self.seq*13)%900))} for i in range(8)],label='Synthetic depth · not exchange orders')
