"""FastAPI application. Run one market publisher/worker per database deployment."""
import asyncio,logging,time
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException,Header,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from api.config import Settings
from api.storage import Store
from data_ingestion.market import Market
from matching_engine.broker import Broker
from matching_engine.schemas import AccountCreate,OrderRequest
from matching_engine.calendar import market_status
from models.predictor import Predictor,correlate
from models.options import black_scholes,implied_volatility

log=logging.getLogger(__name__)

def create_app(settings=None):
    cfg=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        store=Store(cfg.database_url);market=Market(cfg,store);broker=Broker(store,market,cfg)
        app.state.store=store;app.state.market=market;app.state.broker=broker;app.state.predictions={}
        await market.initialize();task=asyncio.create_task(market.run(broker));app.state.task=task
        try:yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            if market.redis:await market.redis.aclose()
            store.close()
    app=FastAPI(title='StockTracker',version='1.0.0',lifespan=lifespan)
    @app.middleware('http')
    async def headers(request,call_next):
        response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='same-origin'
        if request.url.path.startswith('/api/accounts'):response.headers['Cache-Control']='no-store'
        return response
    @app.exception_handler(PermissionError)
    async def denied(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Unknown account or invalid access key'},status_code=403)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':str(exc)},status_code=422)
    def key(header):return header.removeprefix('Bearer ') if header and header.startswith('Bearer ') else ''
    @app.get('/api/health')
    def health():
        m=app.state.market
        fresh=[s for s,q in m.quotes.items() if 0<=time.time()-q['time']<30]
        return dict(status='ready' if fresh and not app.state.task.done() and not m.error else 'degraded',mode=cfg.mode,collector_running=not app.state.task.done(),last_success=m.last_success,error=m.error,cache=m.cache_status,fresh_symbols=fresh,session=market_status(),token_usd=1)
    @app.get('/api/market')
    def market():return dict(symbols=app.state.market.symbols,quotes=app.state.market.quotes,mode=cfg.mode)
    @app.get('/api/market/{symbol}')
    def instrument(symbol:str):
        m=app.state.market
        if symbol not in m.symbols:raise HTTPException(404,'Symbol not configured')
        bars=m.bars[symbol];news=m.news(symbol);cache=app.state.predictions.get(symbol);minute=int(time.time()//60)
        if not cache or cache[0]!=minute:
            result=Predictor().predict(bars,news,demo=cfg.mode=='demo');app.state.predictions[symbol]=(minute,result)
        else:result=cache[1]
        return dict(symbol=symbol,bars=bars,news=news,depth=m.depth(symbol),prediction=result,correlation=correlate(bars,news),volatility=m.volatility(symbol),mode=cfg.mode)
    @app.post('/api/accounts',status_code=201)
    def create(body:AccountCreate):
        state,token=app.state.broker.create(body.name,body.initial_tokens)
        return dict(account=state,access_key=token)
    @app.get('/api/accounts/{id}')
    def account(id:str,authorization:str|None=Header(None)):return app.state.broker.snapshot(id,key(authorization))
    @app.post('/api/accounts/{id}/orders',status_code=201)
    def order(id:str,body:OrderRequest,authorization:str|None=Header(None)):
        return app.state.broker.submit(id,key(authorization),body)
    @app.delete('/api/accounts/{id}/orders/{client_id}')
    def cancel(id:str,client_id:str,authorization:str|None=Header(None)):return app.state.broker.cancel(id,key(authorization),client_id)
    class OptionInput(BaseModel):
        spot:float=Field(gt=0,le=1000000);strike:float=Field(gt=0,le=1000000);days:float=Field(ge=0,le=366);vol:float=Field(gt=0,le=5);right:str='call';observed_premium:float|None=Field(None,gt=0)
    @app.post('/api/options/price')
    def option(body:OptionInput):
        result=black_scholes(body.spot,body.strike,body.days/365,body.vol,body.right)
        result.update(model='Hypothetical European cash-settled',volatility_source='User assumption / realized-vol proxy; not observed IV',multiplier=100)
        if body.observed_premium is not None:result['implied_volatility']=implied_volatility(body.observed_premium,body.spot,body.strike,body.days/365,body.right)
        return result
    @app.websocket('/ws/market')
    async def socket(ws:WebSocket):
        m=app.state.market
        if len(m.listeners)>=100:await ws.close(code=1013);return
        await ws.accept();queue=asyncio.Queue(maxsize=2);m.listeners.add(queue)
        receiver=asyncio.create_task(ws.receive())
        try:
            await ws.send_json(dict(type='quotes',quotes=m.quotes,mode=cfg.mode,seq=m.seq))
            while True:
                incoming=asyncio.create_task(queue.get())
                done,_=await asyncio.wait([incoming,receiver],timeout=15,return_when=asyncio.FIRST_COMPLETED)
                if receiver in done:
                    if not incoming.done():incoming.cancel()
                    event=receiver.result()
                    if event['type']=='websocket.disconnect':break
                    receiver=asyncio.create_task(ws.receive())
                if incoming in done:await ws.send_json(incoming.result())
                elif not incoming.done():
                    incoming.cancel()
                    await ws.send_json({'type':'heartbeat','time':time.time()})
        except (WebSocketDisconnect,RuntimeError):pass
        finally:
            receiver.cancel();m.listeners.discard(queue)
    dist=Path(__file__).resolve().parents[1]/'ui/dist'
    if (dist/'assets').exists():app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    @app.get('/')
    def index():
        if not (dist/'index.html').exists():raise HTTPException(503,'Build the UI: cd ui && npm ci && npm run build')
        return FileResponse(dist/'index.html')
    return app

app=create_app()
