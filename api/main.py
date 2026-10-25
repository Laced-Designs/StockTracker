import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
import structlog
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from core.config import Settings
from core.db import DuckDBStore
from core.models import OHLCV
from engine.patterns import PatternEngine
from features.indicators import vpvr
from ingestion.demo import demo_bars
from ingestion.live import AlpacaStream, MinuteAggregator
from core.history import HistoryCatalog
from engine.research import series_catalog,load_series
from engine.options import OptionScenario,analyze_option

log=structlog.get_logger()

class ImportBars(BaseModel):
    bars: list[OHLCV] = Field(min_length=1,max_length=10000)

def create_app(settings=None):
    settings=settings or Settings()
    queues=set()
    @asynccontextmanager
    async def lifespan(app):
        store=DuckDBStore(settings.database_path)
        app.state.store=store
        app.state.catalog=HistoryCatalog(store)
        app.state.stream_error=None
        if settings.demo and store.bars("SPY",source="synthetic").empty:
            await asyncio.to_thread(store.upsert_bars,demo_bars())
        task=None
        if not settings.demo and settings.alpaca_key and settings.alpaca_secret:
            aggregator=MinuteAggregator()
            async def on_tick(tick):
                inserted=await asyncio.to_thread(store.tick,tick)
                if not inserted: return
                bar=aggregator.add(tick)
                if bar is None: return
                await asyncio.to_thread(store.upsert_bars,[bar])
                try:
                    signal=await asyncio.to_thread(compute,tick.symbol,"1m",tick.source)
                except ValueError: return
                for queue in tuple(queues):
                    if queue.full(): queue.get_nowait()
                    queue.put_nowait(signal.model_dump(mode="json"))
            async def stream():
                try:
                    await AlpacaStream(settings.alpaca_key,settings.alpaca_secret,["SPY"]).run(on_tick)
                except Exception as exc:
                    app.state.stream_error=type(exc).__name__
                    log.error("stream_stopped",error_type=type(exc).__name__)
            task=asyncio.create_task(stream())
        yield
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        store.close()
    app=FastAPI(title="MarketPulse",version="0.1.0",lifespan=lifespan)
    def compute(symbol,interval,source):
        frame=app.state.store.bars(symbol,interval,source=source)
        if frame.empty: raise ValueError("no data for selected symbol/source/interval")
        mode="synthetic" if frame.source.iloc[-1]=="synthetic" else "historical"
        if frame.source.iloc[-1]=="alpaca_iex" and (datetime.now(timezone.utc)-frame.timestamp.iloc[-1]).total_seconds()<180:
            mode="live"
        signal=PatternEngine(frame,settings.window,settings.neighbors).predict(mode=mode)
        signal.alert=any(p.samples>=10 and p.interval_95 and (p.interval_95[0]>.5 or p.interval_95[1]<.5) and max(p.probability_up,1-p.probability_up)>=settings.alert_threshold for p in signal.predictions)
        app.state.store.signal(signal)
        return signal
    @app.get("/",response_class=HTMLResponse)
    def dashboard(): return Path(__file__).with_name("research.html").read_text()
    @app.get("/terminal",response_class=HTMLResponse)
    def terminal(): return Path(__file__).with_name("dashboard.html").read_text()
    @app.get('/research',response_class=HTMLResponse)
    def research_dashboard(): return Path(__file__).with_name('research.html').read_text()
    @app.get('/guide/options',response_class=HTMLResponse)
    def options_guide(): return Path(__file__).with_name('options_guide.html').read_text()
    @app.post('/api/options/scenario')
    def option_scenario(body:OptionScenario): return analyze_option(body)
    @app.get('/api/history/coverage')
    def history_coverage():
        return {'series':app.state.catalog.coverage().to_dict(orient='records'),
            'jobs':app.state.catalog.jobs().to_dict(orient='records'),
            'gap_note':'Observed calendar gaps are diagnostic, not an exchange-calendar missing-session count.'}
    @app.get('/api/research/latest')
    def latest_research():
        return app.state.catalog.latest_report() or {'status':'not_run','message':'Run cli.py research against this database.'}
    @app.get('/api/history/prices/{symbol}')
    def history_prices(symbol:str,source:str|None=None,limit:int=Query(1000,ge=1,le=20000)):
        choices=series_catalog(app.state.store)
        choices=choices[choices.symbol==symbol.upper()]
        if source is not None:choices=choices[choices.source==source]
        if len(choices)!=1:raise HTTPException(422,'Choose exactly one source for an available daily series')
        return {'source':choices.source.iloc[0],'prices':load_series(app.state.store,choices.source.iloc[0],symbol.upper()).tail(limit)[['timestamp','close']].to_dict(orient='records')}
    @app.get("/health")
    def health(): return {"status":"ok","demo":settings.demo,"stream_error":app.state.stream_error}
    @app.get("/api/bars/{symbol}")
    def bars(symbol:str,interval:str="1m",source:str|None=None,limit:int=Query(400,ge=1,le=20000)):
        try:
            frame=app.state.store.bars(symbol.upper(),interval,limit,source)
            return {"bars":frame.to_dict(orient="records")}
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    @app.post("/api/bars")
    def import_bars(body:ImportBars):
        return {"processed":app.state.store.upsert_bars(body.bars)}
    @app.get("/api/signals/{symbol}")
    def signals(symbol:str,interval:str="1m",source:str|None=None):
        try: return compute(symbol.upper(),interval,source)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    @app.get("/api/backtest/{symbol}")
    def backtest(symbol:str,interval:str="1m",source:str|None=None):
        try: return PatternEngine(app.state.store.bars(symbol.upper(),interval,source=source),settings.window,settings.neighbors).backtest()
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    @app.get("/api/profile/{symbol}")
    def profile(symbol:str,source:str|None=None):
        try:
            frame=app.state.store.bars(symbol.upper(),source=source)
            if frame.empty: raise ValueError("no data")
            return vpvr(frame)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    @app.websocket("/ws/signals/{symbol}")
    async def websocket(ws:WebSocket,symbol:str,source:str|None=None):
        await ws.accept()
        queue=asyncio.Queue(maxsize=8)
        queues.add(queue)
        try:
            initial=await asyncio.to_thread(compute,symbol.upper(),"1m",source)
            await ws.send_json(initial.model_dump(mode="json"))
            # Wait for actual finalized bars; demo never masquerades as a live feed.
            receiver=asyncio.create_task(ws.receive())
            try:
                while True:
                    incoming=asyncio.create_task(queue.get())
                    try:
                        done,_=await asyncio.wait({receiver,incoming},timeout=20,return_when=asyncio.FIRST_COMPLETED)
                        if receiver in done:
                            event=receiver.result()
                            if event["type"]=="websocket.disconnect": break
                            receiver=asyncio.create_task(ws.receive())
                        if incoming in done:
                            payload=incoming.result()
                            if payload["symbol"]==symbol.upper() and source in (None,"alpaca_iex"):
                                await ws.send_json(payload)
                        elif not done:
                            await ws.send_json({"type":"heartbeat","demo":settings.demo})
                    finally:
                        if not incoming.done():
                            incoming.cancel()
                            try: await incoming
                            except asyncio.CancelledError: pass
            finally:
                receiver.cancel()
                try: await receiver
                except asyncio.CancelledError: pass
        except ValueError as exc:
            await ws.send_json({"error":str(exc)});await ws.close(code=1008)
        except WebSocketDisconnect: pass
        finally: queues.discard(queue)
    return app

app=create_app()
