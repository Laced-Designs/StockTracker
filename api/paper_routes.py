from pathlib import Path
from fastapi import APIRouter,HTTPException,Header,Request
from fastapi.responses import HTMLResponse
from paper.models import AccountRequest,OrderRequest
from paper.replay import HistoricalReplay
from paper.analytics import account_analytics

router=APIRouter()

def auth(request,account_id,authorization):
    token=authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    try:request.app.state.paper.authorize(account_id,token)
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc

@router.get('/paper',response_class=HTMLResponse)
def lab():return Path(__file__).with_name('paper.html').read_text()

@router.post('/api/paper/accounts',status_code=201)
def create_account(body:AccountRequest,request:Request):
    paper=request.app.state.paper
    try:
        if body.mode=='replay':a,key=HistoricalReplay(paper).create(body)
        else:a,key=paper.create(body.name,'live',body.initial_tokens)
        return {'account':a,'access_key':key,'valuation':paper.valuation(a['id'])}
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.get('/api/paper/accounts/{account_id}')
def account(account_id:str,request:Request,authorization:str|None=Header(default=None)):
    auth(request,account_id,authorization)
    return {'account':request.app.state.paper.get(account_id),'analytics':account_analytics(request.app.state.paper,account_id),'orders':request.app.state.paper.orders(account_id)}

@router.post('/api/paper/accounts/{account_id}/orders',status_code=201)
def order(account_id:str,body:OrderRequest,request:Request,authorization:str|None=Header(default=None)):
    auth(request,account_id,authorization)
    try:return request.app.state.paper.submit(account_id,body)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.delete('/api/paper/accounts/{account_id}/orders/{client_order_id}')
def cancel(account_id:str,client_order_id:str,request:Request,authorization:str|None=Header(default=None)):
    auth(request,account_id,authorization)
    try:request.app.state.paper.cancel(account_id,client_order_id);return {'status':'canceled'}
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.post('/api/paper/accounts/{account_id}/advance')
def advance(account_id:str,request:Request,authorization:str|None=Header(default=None)):
    auth(request,account_id,authorization)
    try:return HistoricalReplay(request.app.state.paper).advance(account_id)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.get('/api/paper/accounts/{account_id}/history')
def history(account_id:str,request:Request,authorization:str|None=Header(default=None)):
    auth(request,account_id,authorization)
    paper=request.app.state.paper
    visible=HistoricalReplay(paper).visible_prices(account_id) if paper.get(account_id)['mode']=='replay' else []
    return {'events':paper.history(account_id),'visible_prices':visible}

@router.get('/api/paper/challenge')
def challenge(request:Request):return request.app.state.challenge.status()


@router.get('/api/paper/rehearsal')
def rehearsal(request:Request):
    import json
    store=request.app.state.store
    with store.lock:row=store.conn.execute('SELECT summary FROM paper_trials ORDER BY created_at DESC LIMIT 1').fetchone()
    return json.loads(row[0]) if row else {'status':'not_run','summary':[]}
