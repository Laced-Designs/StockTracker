"""Public experiment overview; private user accounts never enter the leaderboard."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from fastapi import APIRouter, Request
from paper.week_study import WeekStudy

router = APIRouter()

@router.get('/api/overview')
def overview(request: Request):
    state = request.app.state
    now = datetime.now(timezone.utc)
    study = WeekStudy(state.store).status()
    services = {name: 'stopped' if task.done() else 'running'
                for name, task in state.collectors.items()}
    ready = state.challenge.readiness()
    fresh = ready['fresh_crypto_symbols'] + ready['fresh_stock_symbols']
    accounts = [('seven-day-agent', 'Original challenge', 'Challenge')]
    with state.store.lock:
        arms = state.store.conn.execute('SELECT account_id,symbol,policy FROM paper_study_arms WHERE study_id=?', [study['plan']['id']]).fetchall()
    accounts += [(a, s + ' · ' + p.replace('_', ' '), 'Live paper study') for a, s, p in arms]
    board, activity = [], []
    for account_id, name, lane in accounts:
        account = state.paper.get(account_id)
        value = state.paper.valuation(account_id)
        orders = state.paper.orders(account_id)
        fills = [o for o in orders if o['status'] == 'filled']
        equity = value['equity_tokens']
        board.append(dict(name=name, lane=lane, equity_tokens=equity,
            pnl_tokens=str(Decimal(equity)-Decimal(account['initial_tokens'])) if equity is not None else None,
            fees_tokens=account['fees_tokens'], fills=len(fills),
            pending=sum(o['status']=='pending' for o in orders), asof=value['asof'],
            status='Unpriced' if equity is None else 'Trading' if fills else 'Not started',
            target_tokens=account.get('target_tokens')))
        for event in state.paper.history(account_id):
            if event['kind'] in ('fill','order_submitted','order_canceled','order_rejected'):
                activity.append(dict(name=name, **event))
    board.sort(key=lambda r: (r['equity_tokens'] is None, -Decimal(r['equity_tokens'] or '0')))
    latest = study['latest_daily_checks'][-1] if study['latest_daily_checks'] else None
    tasks = [dict(title=c['focus'], day=c['day'],
        status='Completed' if c['day'] in study['days_recorded'] else 'Missing' if c['day'] in study['missing_due_days'] else 'Scheduled',
        href='/tasks') for c in study['plan']['checkpoints']]
    return dict(asof=now.isoformat(), services=services,
        collection_status='Running' if services.get('study')=='running' else 'Stopped' if 'study' in services else 'Disabled',
        feed_status='Fresh quotes available' if fresh else 'No fresh eligible quotes', fresh_symbols=fresh,
        last_quote_success=state.paper_feed['last_success'], feed_error=state.paper_feed['error'],
        leaderboard=board, activity=sorted(activity,key=lambda e:e['timestamp'],reverse=True)[:40],
        tasks=tasks, last_checkpoint=latest, missing_days=study['missing_due_days'],
        study_end=study['plan']['ends_at'], original_deadline=state.paper.get('seven-day-agent')['deadline'],
        options_status='Blocked: quoted option data and execution are not implemented',
        model_cases=study['options_model'].get('scenarios',0))
